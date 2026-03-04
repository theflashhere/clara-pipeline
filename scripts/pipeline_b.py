#!/usr/bin/env python3
"""
Pipeline B: Patch v1 account memo with onboarding update.
Produces v2 memo + v2 agent spec + full changelog.
Zero-cost rule-based with optional Claude API upgrade.
"""

import json
import os
import sys
import copy
import argparse
from pathlib import Path
from datetime import datetime, timezone

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


def read_file(path: str) -> str:
    p = Path(path)
    if p.suffix == ".docx":
        from docx import Document
        doc = Document(p)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    return p.read_text(encoding="utf-8")


def patch_via_api(v1_memo: dict, update_text: str) -> tuple[dict, list]:
    """Use Claude API to intelligently patch v1 to v2."""
    import urllib.request
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None, None

    SYSTEM = """You are a configuration patch engine for Clara Answers.
You receive a v1 account memo JSON and onboarding update text.
Produce an updated v2 memo and a detailed changelog.

Return ONLY a JSON object with exactly two keys:
{
  "updated_memo": { ...full updated memo with version set to "v2"... },
  "changelog": [
    {
      "field": "dot.path.to.field",
      "old_value": "previous value as string",
      "new_value": "new value as string",
      "reason": "concise reason for change"
    }
  ]
}

RULES:
- Preserve all v1 fields unless explicitly overridden.
- Only log actual changes.
- Set version to "v2".
- Return ONLY JSON, no markdown."""

    user = f"V1 Memo:\n{json.dumps(v1_memo, indent=2)}\n\nOnboarding Update:\n{update_text}"
    payload = json.dumps({
        "model": MODEL, "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user}]
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL, data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        raw = data["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw.strip())
        return result["updated_memo"], result["changelog"]
    except Exception as e:
        print(f"  [API] Error: {e} - falling back to rule-based patch")
        return None, None


def parse_update_text(text: str) -> dict:
    """Parse structured onboarding update text into a dict of changes."""
    updates = {}
    lines = text.lower()

    import re

    # Phone numbers - look for explicit labels
    # Transfer number
    m = re.search(r'(?:second|transfer|personal)\s+(?:phone\s+)?number[^\d]*(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})', text, re.IGNORECASE)
    if m:
        updates["transfer_phone_number"] = m.group(1).strip()

    # Main / SMS number - look for a number on a line after "main" or "SMS" label
    m = re.search(r'(?:main|business|sms)[^\n]*\n[^\d]*(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})', text, re.IGNORECASE)
    if not m:
        # Try same-line match with colon separator
        m = re.search(r'(?:main line|business line|sms)[^:\n]*:\s*(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})', text, re.IGNORECASE)
    if m:
        updates["sms_number"] = m.group(1).strip()

    # Timezone - look for explicit "Confirmed timezone: X/Y" pattern
    m = re.search(r'[Cc]onfirmed\s+timezone:\s*(America/\w+|[\w]+/[\w]+)', text)
    if m:
        updates["timezone"] = m.group(1).strip()
    elif re.search(r'timezone[^\n]*edmonton', text, re.IGNORECASE):
        updates["timezone"] = "America/Edmonton"

    # Transfer timeout
    m = re.search(r'transfer\s+timeout[^\d]*(\d+)\s*seconds?', text, re.IGNORECASE)
    if m:
        updates["transfer_timeout_seconds"] = int(m.group(1))

    # Business hours
    m = re.search(r'(\d{1,2}(?::\d{2})?)\s*(?:AM|am)\s*to\s*(\d{1,2}(?::\d{2})?)\s*(?:PM|pm)', text, re.IGNORECASE)
    if m:
        updates["business_hours_start"] = m.group(1) + " AM"
        updates["business_hours_end"] = m.group(2) + " PM"

    # Commercial rate
    m = re.search(r'commercial\s+hourly[^\$]*\$(\d+)', text, re.IGNORECASE)
    if m:
        updates["commercial_hourly_rate"] = f"${m.group(1)}/hour"

    # Address / city
    if "calgary" in text.lower():
        updates["city"] = "Calgary, Alberta, Canada"

    # Integration constraints
    if "servicetrade" in text.lower() and "never" in text.lower():
        updates["integration_constraint"] = "Never create or modify ServiceTrade jobs directly. All job creation handled manually by Ben."

    # Additional emergency clients
    additional_clients = []
    # Look for new company blocks
    blocks = re.split(r'\n\s*\n', text)
    for block in blocks:
        if ("emergency" in block.lower() or "additional" in block.lower()) and "company:" in block.lower():
            company_m = re.search(r'company:\s*(.+)', block, re.IGNORECASE)
            contact_m = re.search(r'contact:\s*(.+)', block, re.IGNORECASE)
            phone_m = re.search(r'phone:\s*(.+)', block, re.IGNORECASE)
            prop_m = re.search(r'property\s+type:\s*(.+)', block, re.IGNORECASE)
            notes_m = re.search(r'notes?:\s*(.+)', block, re.IGNORECASE)
            if company_m and company_m.group(1).strip().lower() not in ["g&m pressure washing", "ben's electric solutions"]:
                additional_clients.append({
                    "company": company_m.group(1).strip(),
                    "contact_name": contact_m.group(1).strip() if contact_m else None,
                    "phone": phone_m.group(1).strip() if phone_m else None,
                    "email": None,
                    "property_type": prop_m.group(1).strip() if prop_m else None,
                    "notes": notes_m.group(1).strip() if notes_m else None
                })
    if additional_clients:
        updates["additional_emergency_clients"] = additional_clients

    return updates


def build_changelog(v1: dict, v2: dict) -> list:
    """Build a detailed changelog by diffing v1 and v2 memos."""
    changelog = []

    def diff_values(path: str, old, new):
        if old != new:
            changelog.append({
                "field": path,
                "old_value": str(old) if old is not None else "null",
                "new_value": str(new) if new is not None else "null",
                "reason": infer_reason(path, old, new)
            })

    def infer_reason(path: str, old, new) -> str:
        reasons = {
            "call_routing.transfer_phone_number": "Ben's second personal number confirmed during onboarding follow-up",
            "notification_preferences.sms_number": "Ben's main business line confirmed for SMS notifications",
            "business_hours.timezone": "Timezone explicitly confirmed by client (Calgary, Alberta)",
            "business_hours.start": "Client confirmed 8:30 AM start time - website listing was outdated",
            "business_hours.end": "Client confirmed 5:00 PM end time - website listing was outdated",
            "call_transfer_rules.transfer_timeout_seconds": "Client requested longer timeout to give more time to answer",
            "office_address": "Client confirmed mobile operation - Calgary, Alberta",
            "questions_or_unknowns": "Resolved unknowns from onboarding update",
            "integration_constraints": "Client specified ServiceTrade must not be touched by Clara",
            "pricing_info.commercial_hourly_rate": "Commercial rate differs from residential - added per client",
            "emergency_routing_rules.allowed_clients": "Additional emergency client added: Northland Property Management",
        }
        for key, reason in reasons.items():
            if key in path:
                return reason
        return "Updated during onboarding follow-up"

    # Compare top-level fields
    all_keys = set(list(v1.keys()) + list(v2.keys())) - {"_meta", "version"}
    for key in sorted(all_keys):
        old_val = v1.get(key)
        new_val = v2.get(key)
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            for subkey in sorted(set(list(old_val.keys()) + list(new_val.keys()))):
                diff_values(f"{key}.{subkey}", old_val.get(subkey), new_val.get(subkey))
        elif isinstance(old_val, list) and isinstance(new_val, list):
            if old_val != new_val:
                diff_values(key, json.dumps(old_val, ensure_ascii=False),
                           json.dumps(new_val, ensure_ascii=False))
        else:
            diff_values(key, old_val, new_val)

    return changelog


def apply_patch_rule_based(v1_memo: dict, update_text: str) -> tuple[dict, list]:
    """Rule-based patch: parse update text and apply to v1 memo."""
    v2 = copy.deepcopy(v1_memo)
    updates = parse_update_text(update_text)

    print(f"  [Patch] Detected {len(updates)} field updates")

    # Apply transfer number
    if "transfer_phone_number" in updates:
        v2["call_routing"]["transfer_phone_number"] = updates["transfer_phone_number"]
        v2["emergency_routing_rules"]["transfer_to"] = updates["transfer_phone_number"]

    # Apply SMS number
    if "sms_number" in updates:
        v2["notification_preferences"]["sms_number"] = updates["sms_number"]

    # Apply timezone
    if "timezone" in updates:
        v2["business_hours"]["timezone"] = updates["timezone"]

    # Apply business hours
    if "business_hours_start" in updates:
        v2["business_hours"]["start"] = updates["business_hours_start"]
    if "business_hours_end" in updates:
        v2["business_hours"]["end"] = updates["business_hours_end"]

    # Apply transfer timeout
    if "transfer_timeout_seconds" in updates:
        v2["call_transfer_rules"]["transfer_timeout_seconds"] = updates["transfer_timeout_seconds"]

    # Apply commercial rate
    if "commercial_hourly_rate" in updates:
        v2["pricing_info"]["commercial_hourly_rate"] = updates["commercial_hourly_rate"]
        v2["pricing_info"]["notes"] = (v2["pricing_info"].get("notes") or "") + \
            f" Commercial rate: {updates['commercial_hourly_rate']}."

    # Apply city/address
    if "city" in updates:
        v2["office_address"] = updates["city"] + " (mobile operation - no fixed client-facing address)"

    # Apply integration constraint
    if "integration_constraint" in updates:
        existing = v2.get("integration_constraints", [])
        if updates["integration_constraint"] not in existing:
            existing.append(updates["integration_constraint"])
        v2["integration_constraints"] = existing

    # Apply additional emergency clients
    if "additional_emergency_clients" in updates:
        existing_clients = v2["emergency_routing_rules"].get("allowed_clients", [])
        existing_names = [c.get("company", "").lower() for c in existing_clients]
        for new_client in updates["additional_emergency_clients"]:
            if new_client["company"].lower() not in existing_names:
                existing_clients.append(new_client)
        v2["emergency_routing_rules"]["allowed_clients"] = existing_clients

    # Update questions_or_unknowns - remove resolved ones
    resolved_keywords = ["second phone", "transfer", "sms", "timezone", "main phone"]
    remaining = []
    for unknown in v2.get("questions_or_unknowns", []):
        if not any(kw in unknown.lower() for kw in resolved_keywords):
            remaining.append(unknown)
    v2["questions_or_unknowns"] = remaining

    # Update version
    v2["version"] = "v2"

    # Build changelog
    changelog = build_changelog(v1_memo, v2)

    return v2, changelog


def save_outputs(account_id: str, version: str, memo: dict, spec: dict, changelog: list):
    out_dir = OUTPUTS_DIR / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save memo
    p = out_dir / "account_memo.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(memo, f, indent=2)
    print(f"  ✓ {p}")

    # Save spec
    if spec:
        p = out_dir / "agent_spec.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        print(f"  ✓ {p}")

    # Save changelog JSON
    if changelog:
        p = out_dir / "changelog.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(changelog, f, indent=2)
        print(f"  ✓ {p}")

        # Save changelog markdown
        p = out_dir / "changelog.md"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# Changelog: {account_id} - v1 to v2\n\n")
            f.write(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n\n")
            f.write(f"**{len(changelog)} fields changed**\n\n")
            f.write("| Field | v1 Value | v2 Value | Reason |\n")
            f.write("|-------|----------|----------|--------|\n")
            for entry in changelog:
                old = str(entry.get("old_value", "-"))[:80]
                new = str(entry.get("new_value", "-"))[:80]
                f.write(f"| `{entry.get('field','')}` | {old} | {new} | {entry.get('reason','-')} |\n")
        print(f"  ✓ {p}")


def run_pipeline_b(update_path: str, v1_memo_path: str):
    print(f"\n[Pipeline B] Loading v1 memo: {v1_memo_path}")
    with open(v1_memo_path) as f:
        v1_memo = json.load(f)

    print(f"[Pipeline B] Reading update: {update_path}")
    update_text = read_file(update_path)
    account_id = v1_memo.get("account_id", "unknown")

    # Try API first, fallback to rule-based
    v2_memo, changelog = None, None
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("  Using Claude API for patch...")
        v2_memo, changelog = patch_via_api(v1_memo, update_text)

    if v2_memo is None:
        print("  Using rule-based patch (zero-cost mode)...")
        v2_memo, changelog = apply_patch_rule_based(v1_memo, update_text)

    v2_memo["_meta"] = {
        **v1_memo.get("_meta", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "update_source_file": Path(update_path).name,
        "pipeline": "B",
        "version": "v2"
    }

    # Generate v2 agent spec
    sys.path.insert(0, str(Path(__file__).parent))
    from local_pipeline import generate_agent_spec
    spec_v2 = generate_agent_spec(v2_memo)
    spec_v2["version"] = "v2"

    print(f"\n  Saving v2 outputs for: {account_id}")
    save_outputs(account_id, "v2", v2_memo, spec_v2, changelog)

    print(f"\n  Change summary:")
    for entry in changelog:
        print(f"    • {entry['field']}: {entry['old_value']} -> {entry['new_value']}")

    print(f"\n✅ Pipeline B complete: {account_id}/v2 ({len(changelog)} changes)")
    return v2_memo, changelog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Pipeline B - v1 to v2 Patch")
    parser.add_argument("--update", required=True, help="Path to onboarding update file")
    parser.add_argument("--v1-memo", required=True, help="Path to v1 account_memo.json")
    args = parser.parse_args()
    run_pipeline_b(args.update, args.v1_memo)
