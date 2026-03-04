#!/usr/bin/env python3
"""
Generate Retell Agent Draft Spec from Account Memo JSON.
Produces a structured agent_spec.json with full system prompt.
Zero-cost, template-based with Claude for prompt generation.
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

PROMPT_GEN_SYSTEM = """
You are a voice agent prompt engineer for Clara Answers, a professional AI answering service.
You will receive an account memo JSON and must generate a production-ready system prompt for a Retell AI voice agent.

The prompt MUST follow this exact structure and include ALL of these elements:

1. IDENTITY & CONTEXT section — who the agent is, what company it represents
2. BUSINESS HOURS FLOW section:
   - Warm professional greeting with company name
   - Ask purpose of call
   - Collect caller's name and callback number
   - Route or transfer to the right person
   - If transfer fails: apologize, assure callback, give timeframe
   - Ask "Is there anything else I can help you with?"
   - Close the call warmly

3. AFTER-HOURS FLOW section:
   - Warm greeting, mention office is closed
   - Ask purpose of call
   - Confirm if it is an emergency
   - IF EMERGENCY: collect name, phone, address immediately → attempt transfer → if fails: apologize and assure urgent callback
   - IF NOT EMERGENCY: collect details, confirm follow-up next business day
   - Ask "Is there anything else I can help you with?"
   - Close warmly

4. PRICING section (if applicable) — instructions on when/how to mention pricing
5. TRANSFER PROTOCOL — exact steps when transferring a call
6. FALLBACK PROTOCOL — exact steps when transfer fails
7. CONSTRAINTS — what the agent must never do or say

STRICT RULES:
- Never ask too many questions. Collect only name, number, address, and reason.
- Never mention "function calls", "tools", "AI", or "automation" to the caller.
- Always be warm, professional, and concise.
- If emergency routing is restricted to specific clients, clearly encode that logic.
- Return ONLY the system prompt text. No JSON wrapper, no markdown headers, no backticks.
"""


def call_claude(system: str, user: str) -> str:
    import urllib.request
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 3000,
        "system": system,
        "messages": [{"role": "user", "content": user}]
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


def generate_agent_spec(memo: dict) -> dict:
    """Generate full Retell agent spec from account memo."""
    print(f"  [AgentGen] Generating prompt for: {memo.get('company_name')}")

    # Generate system prompt via Claude
    user_msg = f"""
Account memo:
{json.dumps(memo, indent=2)}

Generate the complete Clara voice agent system prompt for this account.
"""
    system_prompt = call_claude(PROMPT_GEN_SYSTEM, user_msg)

    bh = memo.get("business_hours", {}) or {}
    routing = memo.get("call_routing", {}) or {}
    notif = memo.get("notification_preferences", {}) or {}
    emergency = memo.get("emergency_routing_rules", {}) or {}
    transfer_rules = memo.get("call_transfer_rules", {}) or {}

    agent_spec = {
        "agent_name": f"Clara - {memo.get('company_name', 'Unknown')}",
        "version": memo.get("version", "v1"),
        "account_id": memo.get("account_id"),
        "company_name": memo.get("company_name"),
        "voice_style": {
            "tone": "warm, professional, concise",
            "persona": "Clara, a helpful answering assistant",
            "language": "en-US"
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
            "note": "Do not mention any tools, APIs, or automation to callers.",
            "transfer_call": "Internal action — triggered silently when routing requires it.",
            "send_notification": "Internal action — triggered silently after each call.",
            "log_call": "Internal action — all calls logged to dashboard automatically."
        },
        "call_transfer_protocol": {
            "when": "When caller requests to speak with someone or when routing rules require it",
            "how": "Warm transfer — inform caller they are being connected",
            "timeout_seconds": transfer_rules.get("transfer_timeout_seconds", 30),
            "retry": transfer_rules.get("retry_on_fail", False),
            "transfer_to_number": routing.get("transfer_phone_number")
        },
        "fallback_protocol": {
            "trigger": "Transfer fails or times out",
            "action": transfer_rules.get("what_to_say_if_transfer_fails") or
                      "Apologize sincerely, collect caller details, assure callback within business hours.",
            "collect": ["name", "phone_number", "reason_for_call"],
            "notify_staff": True
        },
        "after_hours_emergency_protocol": {
            "enabled": emergency.get("enabled", False),
            "allowed_clients": emergency.get("allowed_clients", []),
            "transfer_to": emergency.get("transfer_to"),
            "fallback": emergency.get("fallback_if_transfer_fails",
                        "Collect details, apologize, assure urgent callback.")
        },
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_memo_version": memo.get("version", "v1")
        }
    }

    return agent_spec


def load_memo(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_agent_spec(account_id: str, version: str, spec: dict):
    out_dir = OUTPUTS_DIR / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "agent_spec.json"
    with open(out_path, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"  ✓ Saved {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Agent Spec Generator")
    parser.add_argument("--memo", required=True, help="Path to account_memo.json")
    args = parser.parse_args()

    memo = load_memo(args.memo)
    account_id = memo.get("account_id", "unknown")
    version = memo.get("version", "v1")

    spec = generate_agent_spec(memo)
    save_agent_spec(account_id, version, spec)
    print(f"\n✅ Agent spec generated for {account_id} ({version})")
