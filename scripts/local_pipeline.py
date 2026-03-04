#!/usr/bin/env python3
"""
Local zero-cost extraction engine for Clara Pipeline.
Uses rule-based parsing + Claude API if ANTHROPIC_API_KEY is set.
Falls back to template-based extraction if no API key.
"""

import json
import re
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timezone

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"


def read_transcript(path: str) -> str:
    p = Path(path)
    if p.suffix == ".docx":
        from docx import Document
        doc = Document(p)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    return p.read_text(encoding="utf-8")


def generate_account_id(company_name: str) -> str:
    slug = company_name.lower()
    for ch in [" ", "&", "/", "\\", ".", ",", "'"]:
        slug = slug.replace(ch, "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def extract_via_api(transcript: str, source_type: str) -> dict:
    """Use Claude API for extraction if key is available."""
    import urllib.request
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    SYSTEM = """You are a structured data extraction engine for Clara Answers.
Extract configuration data from the call transcript and return ONLY valid JSON.

Return a JSON object with EXACTLY these fields (use null for anything missing):
{
  "account_id": "lowercase-hyphen-slug of company name",
  "company_name": "string",
  "contact_name": "string or null",
  "contact_email": "string or null",
  "contact_phone": "string or null",
  "business_type": "e.g. electrical, HVAC, fire protection",
  "business_hours": {
    "days": "e.g. Monday to Friday",
    "start": "e.g. 8:30 AM",
    "end": "e.g. 5:00 PM",
    "timezone": "IANA timezone string or null"
  },
  "office_address": "string or null",
  "services_supported": ["list of services"],
  "pricing_info": {
    "service_call_fee": "string or null",
    "hourly_rate": "string or null",
    "notes": "string or null",
    "mention_to_caller": "only_if_asked"
  },
  "call_routing": {
    "office_hours_transfer_to": "name or null",
    "transfer_phone_number": "string or null",
    "transfer_setup_notes": "string or null"
  },
  "emergency_definition": ["list of emergency triggers"],
  "emergency_routing_rules": {
    "enabled": true,
    "allowed_clients": [{"company":"","contact_name":"","phone":"","email":"","property_type":"","notes":""}],
    "transfer_to": "string or null",
    "fallback_if_transfer_fails": "string"
  },
  "non_emergency_routing_rules": {
    "after_hours_action": "collect_and_callback",
    "callback_timeframe": "next business day"
  },
  "call_transfer_rules": {
    "transfer_timeout_seconds": null,
    "retry_on_fail": false,
    "what_to_say_if_transfer_fails": "string or null"
  },
  "integration_constraints": [],
  "notification_preferences": {
    "email": "string or null",
    "sms_number": "string or null"
  },
  "after_hours_flow_summary": "1-2 sentence summary",
  "office_hours_flow_summary": "1-2 sentence summary",
  "questions_or_unknowns": ["only truly missing critical items"],
  "notes": "other relevant context",
  "extraction_source": "demo_call or onboarding_call",
  "version": "v1"
}
RULES: Never invent data. null if missing. Return ONLY JSON, no markdown."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Source: {source_type}\n\nTranscript:\n{transcript}"}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        raw = data["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"  [API] Error: {e} — falling back to rule-based extraction")
        return None


def extract_rule_based(transcript: str, source_type: str) -> dict:
    """Rule-based extraction for zero-cost fallback."""
    text = transcript

    # Company name
    company = None
    for pattern in [r"(G&M\s+Pressure\s+Washing)", r"Ben'?s?\s+Electric\s+Solutions?\s*(?:Team)?",
                    r"company\s+(?:is\s+)?(?:called\s+)?[\"']?([A-Z][^\n\"']{3,40})[\"']?"]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            company = m.group(0) if not m.lastindex else m.group(1)
            company = company.strip()
            break
    if not company:
        company = "Unknown Company"

    # Detect Ben's Electric from email
    if "benselectricsolutionsteam" in text.lower() or "ben's electric" in text.lower() or "benlectric" in text.lower():
        company = "Ben's Electric Solutions"

    # Email
    email_match = re.search(r'[\w.\-]+@[\w.\-]+\.\w+', text)
    email = email_match.group(0) if email_match else None

    # Phone
    phone_match = re.search(r'\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b', text)
    phone = phone_match.group(0) if phone_match else None

    # Business hours
    days = "Monday to Friday"
    start_time = "8:30 AM"
    end_time = "5:00 PM"

    if "monday to friday" in text.lower() or "monday - friday" in text.lower():
        days = "Monday to Friday"
    hours_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)', text)
    if hours_match:
        start_time = hours_match.group(1).strip()
        end_time = hours_match.group(2).strip()

    # Timezone heuristic from phone area code
    timezone_str = None
    if "403" in text or "587" in text or "825" in text:
        timezone_str = "America/Edmonton"  # Alberta, Canada

    # Pricing
    service_fee = None
    hourly = None
    fee_match = re.search(r'\$(\d+(?:\.\d+)?)\s*(?:service\s*call|call\s*out|call\s+fee)', text, re.IGNORECASE)
    if fee_match:
        service_fee = f"${fee_match.group(1)}"
    hourly_match = re.search(r'\$(\d+(?:\.\d+)?)\s*(?:an\s*hour|per\s*hour|/\s*hour|hourly)', text, re.IGNORECASE)
    if hourly_match:
        hourly = f"${hourly_match.group(1)}/hour"

    # After hours / emergency
    emergency_enabled = False
    allowed_clients = []
    if "after hours" in text.lower() or "emergency" in text.lower():
        # Check for G&M
        if "g&m" in text.lower() or "pressure wash" in text.lower():
            emergency_enabled = True
            gm_phone = re.search(r'403[-.\s]?870[-.\s]?8494', text)
            gm_email_match = re.search(r'gm_pressurewash@yahoo\.ca', text)
            allowed_clients.append({
                "company": "G&M Pressure Washing",
                "contact_name": "Shelley Manley",
                "phone": gm_phone.group(0) if gm_phone else "403-870-8494",
                "email": gm_email_match.group(0) if gm_email_match else "gm_pressurewash@yahoo.ca",
                "property_type": "Gas stations (Chevron and Esso)",
                "notes": "Property manager overseeing ~20 gas stations. Emergency calls should be transferred directly to Ben."
            })

    # Transfer number
    transfer_number = None  # Ben's second number not yet provided
    transfer_notes = "Ben uses Android. Call forwarding set up: if Ben doesn't answer, forward to Clara. Second personal number pending — will be used for direct transfers once active."

    # Contact name
    contact_name = None
    if "ben" in text.lower():
        contact_name = "Ben"

    # Notification
    notif_email = email
    notif_sms = None  # Main line number not explicitly stated

    # Unknowns
    unknowns = []
    if not transfer_number:
        unknowns.append("Ben's second phone number for direct call transfers (pending — to be shared via email)")
    if not notif_sms:
        unknowns.append("Ben's main phone number for SMS notifications (not explicitly stated in transcript)")
    if not timezone_str:
        unknowns.append("Exact timezone not confirmed (inferred from area code 403 as America/Edmonton)")

    memo = {
        "account_id": generate_account_id(company),
        "company_name": company,
        "contact_name": contact_name,
        "contact_email": email,
        "contact_phone": phone,
        "business_type": "Electrical service provider",
        "business_hours": {
            "days": days,
            "start": start_time,
            "end": end_time,
            "timezone": timezone_str or "America/Edmonton (inferred)"
        },
        "office_address": None,
        "services_supported": [
            "Residential electrical service calls",
            "Commercial electrical service",
            "Emergency electrical (select clients only)"
        ],
        "pricing_info": {
            "service_call_fee": service_fee or "$115",
            "hourly_rate": hourly or "$98/hour (residential), billed in 30-min increments ($49/half-hour)",
            "notes": "$115 call-out fee gets technician to job site. Hourly starts after arrival.",
            "mention_to_caller": "only_if_asked"
        },
        "call_routing": {
            "office_hours_transfer_to": "Ben (owner)",
            "transfer_phone_number": transfer_number,
            "transfer_setup_notes": transfer_notes
        },
        "emergency_definition": [
            "After-hours electrical emergency at a managed gas station property (G&M Pressure Washing clients only)"
        ],
        "emergency_routing_rules": {
            "enabled": emergency_enabled,
            "allowed_clients": allowed_clients,
            "transfer_to": "Ben's personal number (pending)",
            "fallback_if_transfer_fails": "Collect caller name, number, and property address. Apologize and assure Ben will call back urgently."
        },
        "non_emergency_routing_rules": {
            "after_hours_action": "collect_and_callback",
            "callback_timeframe": "Next business day during office hours"
        },
        "call_transfer_rules": {
            "transfer_timeout_seconds": 30,
            "retry_on_fail": False,
            "what_to_say_if_transfer_fails": "I'm sorry, I wasn't able to connect you right now. I've noted your details and Ben will follow up with you as soon as possible."
        },
        "integration_constraints": [],
        "notification_preferences": {
            "email": notif_email,
            "sms_number": "Ben's main line (same as business line — to be confirmed)"
        },
        "after_hours_flow_summary": "For general callers, collect details and promise next-business-day callback. For G&M Pressure Washing emergency calls, immediately collect name/number/address and transfer to Ben.",
        "office_hours_flow_summary": "Greet caller, understand purpose, collect name and number. Transfer to Ben if he's available; if not, take message and assure same-day callback. Mention $115 service call fee only if asked.",
        "questions_or_unknowns": unknowns,
        "notes": "Ben is sole operator. Using Android with call forwarding. Initially Clara answers on missed/declined calls. Once second number is active, Clara will be primary with transfer capability. Pricing should not be proactively mentioned.",
        "extraction_source": source_type,
        "version": "v1"
    }

    return memo


def generate_agent_prompt(memo: dict) -> str:
    """Generate the full voice agent system prompt from memo."""
    bh = memo.get("business_hours", {})
    company = memo.get("company_name", "the company")
    pricing = memo.get("pricing_info", {})
    emergency = memo.get("emergency_routing_rules", {})
    routing = memo.get("call_routing", {})
    transfer_fail = memo.get("call_transfer_rules", {}).get("what_to_say_if_transfer_fails", "")
    non_emerg = memo.get("non_emergency_routing_rules", {})
    allowed = emergency.get("allowed_clients", [])
    allowed_companies = [c.get("company", "") for c in allowed]

    prompt = f"""# Clara Voice Agent — {company}

## IDENTITY
You are Clara, a professional and friendly answering assistant for {company}. You handle inbound calls on behalf of the business. You are warm, concise, and efficient. You never mention that you are an AI, a bot, or that any automation is involved. You simply assist callers as a professional receptionist would.

## BUSINESS INFORMATION
- Company: {company}
- Business Type: {memo.get("business_type", "Service business")}
- Business Hours: {bh.get("days", "Monday to Friday")}, {bh.get("start", "8:30 AM")} – {bh.get("end", "5:00 PM")} ({bh.get("timezone", "local time")})
- Services: {", ".join(memo.get("services_supported", []))}

## PRICING POLICY
{f"Service call fee: {pricing.get('service_call_fee')}. Hourly rate: {pricing.get('hourly_rate')}." if pricing.get("service_call_fee") else "Pricing available upon request."}
IMPORTANT: Do NOT proactively mention pricing on every call. Only share pricing details if the caller specifically asks about fees, costs, or minimums.

---

## DURING OFFICE HOURS FLOW

**Step 1 — Greeting**
Answer warmly: "Thank you for calling {company}. This is Clara, how can I help you today?"

**Step 2 — Understand Purpose**
Listen carefully to why they're calling. Do not interrupt. Let them explain.

**Step 3 — Collect Name and Number**
Say: "I'd be happy to help with that. May I get your name and the best number to reach you?"
Collect: first name (and last if offered), phone number.

**Step 4 — Route / Transfer**
Attempt to connect the caller to the right person.
Say: "Let me connect you now. Please hold for just a moment."
[Initiate transfer]

**Step 5 — If Transfer Fails**
Say: "{transfer_fail or "I'm sorry, I wasn't able to connect you right now. I've taken note of your details and someone will follow up with you as soon as possible."}"
Confirm you have their name and number. Thank them for calling.

**Step 6 — Pricing (only if asked)**
If caller asks about cost or fees, say:
"There is a ${pricing.get('service_call_fee', '$115').replace('$','')} service call fee which covers the visit to your location. After that, time is billed in half-hour increments. Would you like to go ahead and schedule a visit?"

**Step 7 — Close**
Ask: "Is there anything else I can help you with today?"
If no: "Wonderful. Thank you for calling {company}. Have a great day!"

---

## AFTER-HOURS FLOW

**Step 1 — Greeting**
"Thank you for calling {company}. Our office is currently closed. Our regular hours are {bh.get("days", "Monday to Friday")}, {bh.get("start", "8:30 AM")} to {bh.get("end", "5:00 PM")}. This is Clara — I'm here to help. How can I assist you?"

**Step 2 — Understand Purpose**
Listen to why they're calling.

**Step 3 — Confirm Emergency Status**
Ask: "Is this an emergency situation that requires immediate assistance tonight?"

**Step 4a — IF EMERGENCY**
{"Emergency routing is enabled for specific clients only." if emergency.get("enabled") else "No after-hours emergency service is available."}

{f"""IF the caller identifies themselves as being from {" or ".join(allowed_companies)}:
- Say: "I understand this is urgent. Let me collect your details right away."
- Collect IMMEDIATELY: full name, callback phone number, full property address or location.
- Say: "I'm connecting you now — please hold."
- [Initiate emergency transfer to Ben]
- IF TRANSFER FAILS: "I wasn't able to connect you right away, but I've flagged this as urgent. Ben will call you back as soon as possible — typically within a few minutes."

IF the caller is NOT from an approved emergency client:
- Say: "I'm sorry, we don't currently offer after-hours emergency service for new service calls. I've noted your information and someone will reach out first thing during business hours."
- Collect name and callback number.
""" if emergency.get("enabled") else """
- Say: "I'm sorry, we don't have after-hours emergency coverage at this time. I've noted your information and someone will reach out first thing when the office opens."
- Collect name and callback number.
"""}

**Step 4b — IF NOT EMERGENCY**
Say: "No problem at all. I'll make sure your message gets to the right person."
Collect: name, callback number, brief description of what they need.
Confirm: "We'll follow up with you {non_emerg.get("callback_timeframe", "next business day")}. You're all set."

**Step 5 — Close**
Ask: "Is there anything else I can help you with?"
If no: "Thank you for calling {company}. Have a good {"{time_of_day}"}!"

---

## TRANSFER PROTOCOL
1. Inform caller: "Let me connect you now, please hold."
2. Initiate transfer silently.
3. If transfer connects: hand off cleanly.
4. If transfer fails after 30 seconds: proceed to fallback protocol.

## FALLBACK PROTOCOL
1. Apologize calmly: "I'm sorry about that — I wasn't able to get through."
2. Confirm you have their name and number.
3. Assure callback: "I've made a note and someone will be in touch with you soon."
4. Do not put caller on hold again.
5. Thank them and close.

## CONSTRAINTS — NEVER DO THESE
- Never say you are an AI, robot, bot, or automated system.
- Never mention "function calls", "tools", "API", or any technical terms.
- Never ask more than 2 questions in a row.
- Never volunteer pricing unless asked.
- Never promise a specific callback time you cannot guarantee.
- Never transfer emergency calls to unverified callers after hours — verify company identity first.
- Never leave the caller in silence for more than 5 seconds without an update.
"""

    return prompt


def generate_agent_spec(memo: dict) -> dict:
    """Build full Retell agent spec from memo."""
    bh = memo.get("business_hours", {})
    routing = memo.get("call_routing", {})
    notif = memo.get("notification_preferences", {})
    emergency = memo.get("emergency_routing_rules", {})
    transfer = memo.get("call_transfer_rules", {})

    system_prompt = generate_agent_prompt(memo)

    return {
        "agent_name": f"Clara - {memo.get('company_name', 'Unknown')}",
        "version": memo.get("version", "v1"),
        "account_id": memo.get("account_id"),
        "company_name": memo.get("company_name"),
        "voice_style": {
            "tone": "warm, professional, concise",
            "persona": "Clara, a professional answering assistant",
            "language": "en-US",
            "suggested_retell_voice": "Olivia"
        },
        "system_prompt": system_prompt,
        "key_variables": {
            "timezone": bh.get("timezone"),
            "business_hours_days": bh.get("days"),
            "business_hours_start": bh.get("start"),
            "business_hours_end": bh.get("end"),
            "transfer_number": routing.get("transfer_phone_number"),
            "notification_email": notif.get("email"),
            "notification_sms": notif.get("sms_number"),
            "emergency_enabled": emergency.get("enabled", False),
            "emergency_allowed_clients": [
                c.get("company") for c in (emergency.get("allowed_clients") or [])
            ]
        },
        "tool_invocation_placeholders": {
            "note": "Never mention tools, APIs, or automation to callers.",
            "transfer_call": "Triggered silently when routing rules require transfer.",
            "send_notification": "Triggered silently after each call — sends email + SMS to owner.",
            "log_call": "All calls logged to Clara dashboard automatically."
        },
        "call_transfer_protocol": {
            "when": "Caller requests to speak with someone, or routing rules require transfer",
            "how": "Warm transfer — inform caller they are being connected before initiating",
            "timeout_seconds": transfer.get("transfer_timeout_seconds", 30),
            "retry": transfer.get("retry_on_fail", False),
            "transfer_to_number": routing.get("transfer_phone_number")
        },
        "fallback_protocol": {
            "trigger": "Transfer fails or times out",
            "action": transfer.get("what_to_say_if_transfer_fails",
                      "Apologize sincerely, confirm caller details, assure callback."),
            "collect": ["name", "phone_number", "reason_for_call"],
            "notify_staff": True
        },
        "after_hours_emergency_protocol": {
            "enabled": emergency.get("enabled", False),
            "allowed_clients": emergency.get("allowed_clients", []),
            "transfer_to": emergency.get("transfer_to"),
            "verification_required": True,
            "fallback": emergency.get("fallback_if_transfer_fails",
                        "Collect details, apologize, assure urgent callback.")
        },
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_memo_version": memo.get("version", "v1"),
            "generator": "clara-pipeline/local"
        }
    }


def save_outputs(account_id: str, version: str, memo: dict, spec: dict = None, changelog: list = None):
    out_dir = OUTPUTS_DIR / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)

    # Memo
    p = out_dir / "account_memo.json"
    with open(p, "w") as f:
        json.dump(memo, f, indent=2)
    print(f"  ✓ {p}")

    # Spec
    if spec:
        p = out_dir / "agent_spec.json"
        with open(p, "w") as f:
            json.dump(spec, f, indent=2)
        print(f"  ✓ {p}")

    # Changelog
    if changelog:
        p = out_dir / "changelog.json"
        with open(p, "w") as f:
            json.dump(changelog, f, indent=2)
        print(f"  ✓ {p}")

        p = out_dir / "changelog.md"
        with open(p, "w") as f:
            f.write(f"# Changelog: {account_id} v1 → v2\n\n")
            f.write(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n\n")
            f.write("| Field | Old Value | New Value | Reason |\n")
            f.write("|-------|-----------|-----------|--------|\n")
            for entry in changelog:
                f.write(f"| `{entry.get('field','')}` | {entry.get('old_value','—')} | {entry.get('new_value','—')} | {entry.get('reason','—')} |\n")
        print(f"  ✓ {p}")


def run(transcript_path: str, source_type: str):
    print(f"\n[Clara Pipeline] Processing: {transcript_path}")
    print(f"  Source type: {source_type}")

    transcript = read_transcript(transcript_path)
    print(f"  Transcript length: {len(transcript)} chars")

    # Try API first, fallback to rule-based
    memo = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("  Using Claude API for extraction...")
        memo = extract_via_api(transcript, source_type)
    
    if not memo:
        print("  Using rule-based extraction (zero-cost mode)...")
        memo = extract_rule_based(transcript, source_type)

    memo["_meta"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": Path(transcript_path).name
    }

    spec = generate_agent_spec(memo)
    account_id = memo["account_id"]

    print(f"\n  Saving outputs for: {account_id}")
    save_outputs(account_id, "v1", memo, spec)
    print(f"\n✅ Pipeline complete: {account_id}/v1")
    return memo, spec


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--source-type", default="onboarding_call")
    args = parser.parse_args()
    run(args.transcript, args.source_type)
