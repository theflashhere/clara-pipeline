#!/usr/bin/env python3
"""
Pipeline A + B: Extract Account Memo JSON from call transcripts.
Uses Claude API (free via Anthropic) for intelligent extraction.
Zero-cost, repeatable, idempotent.
"""

import json
import os
import sys
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

EXTRACTION_SYSTEM_PROMPT = """
You are a structured data extraction engine for Clara Answers, an AI voice agent platform.
Your job is to extract configuration data from call transcripts and return ONLY valid JSON.

Return a JSON object with EXACTLY these fields (use null for anything missing):
{
  "account_id": "auto-generated slug from company name",
  "company_name": "string",
  "contact_name": "string or null",
  "contact_email": "string or null",
  "contact_phone": "string or null",
  "business_type": "string (e.g. electrical, HVAC, fire protection)",
  "business_hours": {
    "days": "e.g. Monday to Friday",
    "start": "e.g. 8:30 AM",
    "end": "e.g. 5:00 PM",
    "timezone": "e.g. America/Edmonton or null if unknown"
  },
  "office_address": "string or null",
  "services_supported": ["list", "of", "services"],
  "pricing_info": {
    "service_call_fee": "string or null",
    "hourly_rate": "string or null",
    "notes": "string or null",
    "mention_to_caller": "only_if_asked | always | never"
  },
  "call_routing": {
    "office_hours_transfer_to": "name/number or null",
    "transfer_phone_number": "string or null",
    "transfer_setup_notes": "string or null"
  },
  "emergency_definition": ["list of what counts as emergency"],
  "emergency_routing_rules": {
    "enabled": true or false,
    "allowed_clients": [
      {
        "company": "string",
        "contact_name": "string or null",
        "phone": "string or null",
        "email": "string or null",
        "property_type": "string or null",
        "notes": "string or null"
      }
    ],
    "transfer_to": "string or null",
    "fallback_if_transfer_fails": "string"
  },
  "non_emergency_routing_rules": {
    "after_hours_action": "collect_and_callback | voicemail | other",
    "callback_timeframe": "string e.g. next business day"
  },
  "call_transfer_rules": {
    "transfer_timeout_seconds": null,
    "retry_on_fail": false,
    "what_to_say_if_transfer_fails": "string or null"
  },
  "integration_constraints": ["list of constraints or empty array"],
  "notification_preferences": {
    "email": "string or null",
    "sms_number": "string or null"
  },
  "after_hours_flow_summary": "1-2 sentence summary",
  "office_hours_flow_summary": "1-2 sentence summary",
  "questions_or_unknowns": ["list only truly missing critical items"],
  "notes": "any other relevant context",
  "extraction_source": "demo_call | onboarding_call | onboarding_form",
  "version": "v1"
}

RULES:
- Never invent data. If something is not stated, use null.
- questions_or_unknowns should only list things that ARE missing but ARE critical for agent operation.
- Be precise with phone numbers, emails, business hours exactly as stated.
- account_id should be lowercase-hyphenated slug of company name.
- Return ONLY the JSON object. No explanation, no markdown, no backticks.
"""

PATCH_SYSTEM_PROMPT = """
You are a configuration patch engine for Clara Answers.
You receive an existing v1 account memo JSON and new onboarding data (transcript or form).
Your job is to produce an updated v2 memo and a changelog.

Return ONLY a JSON object with exactly two keys:
{
  "updated_memo": { ...the full updated account memo with version set to "v2"... },
  "changelog": [
    {
      "field": "field path e.g. business_hours.start",
      "old_value": "previous value",
      "new_value": "updated value",
      "reason": "why this changed"
    }
  ]
}

RULES:
- Preserve all existing fields unless new data explicitly overrides them.
- Never remove fields unless the new data explicitly says to.
- Do not invent changes. Only log what actually changed.
- If a field was null in v1 and is now filled, log it as a change.
- Set version to "v2" in the updated memo.
- Return ONLY the JSON. No explanation, no markdown, no backticks.
"""


def read_transcript(path: str) -> str:
    """Read transcript from .txt, .docx, or .md file."""
    p = Path(path)
    if p.suffix == ".docx":
        try:
            from docx import Document
            doc = Document(p)
            return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        except ImportError:
            print("python-docx not installed. Run: pip install python-docx --break-system-packages")
            sys.exit(1)
    else:
        return p.read_text(encoding="utf-8")


def call_claude(system: str, user: str) -> str:
    """Call Claude API and return text response."""
    import urllib.request
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 4000,
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


def safe_parse_json(raw: str) -> dict:
    """Parse JSON safely, stripping markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw.strip())


def generate_account_id(company_name: str) -> str:
    """Generate a stable slug from company name."""
    slug = company_name.lower()
    for ch in [" ", "&", "/", "\\", ".", ","]:
        slug = slug.replace(ch, "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def run_pipeline_a(transcript_path: str, source_type: str = "onboarding_call") -> dict:
    """Pipeline A: Extract v1 account memo from transcript."""
    print(f"\n[Pipeline A] Reading transcript: {transcript_path}")
    transcript = read_transcript(transcript_path)

    print("[Pipeline A] Extracting structured data via Claude...")
    user_msg = f"""
Call type: {source_type}
Transcript:
---
{transcript}
---
Extract the account memo JSON from this transcript.
"""
    raw = call_claude(EXTRACTION_SYSTEM_PROMPT, user_msg)
    memo = safe_parse_json(raw)

    # Ensure account_id is set
    if not memo.get("account_id") and memo.get("company_name"):
        memo["account_id"] = generate_account_id(memo["company_name"])

    # Add metadata
    memo["_meta"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": Path(transcript_path).name,
        "pipeline": "A",
        "version": "v1"
    }
    memo["extraction_source"] = source_type
    memo["version"] = "v1"

    return memo


def run_pipeline_b(onboarding_path: str, v1_memo: dict, source_type: str = "onboarding_call") -> tuple[dict, list]:
    """Pipeline B: Patch v1 memo with onboarding data, produce v2 + changelog."""
    print(f"\n[Pipeline B] Reading onboarding input: {onboarding_path}")
    onboarding_text = read_transcript(onboarding_path)

    print("[Pipeline B] Generating v2 patch via Claude...")
    user_msg = f"""
Existing v1 account memo:
{json.dumps(v1_memo, indent=2)}

New onboarding data (source: {source_type}):
---
{onboarding_text}
---

Produce the updated v2 memo and changelog.
"""
    raw = call_claude(PATCH_SYSTEM_PROMPT, user_msg)
    result = safe_parse_json(raw)

    v2_memo = result["updated_memo"]
    changelog = result["changelog"]

    v2_memo["_meta"] = {
        **v1_memo.get("_meta", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "onboarding_source_file": Path(onboarding_path).name,
        "pipeline": "B",
        "version": "v2"
    }
    v2_memo["version"] = "v2"

    return v2_memo, changelog


def save_outputs(account_id: str, version: str, memo: dict, agent_spec: dict = None, changelog: list = None):
    """Save all artifacts for an account version."""
    version_dir = OUTPUTS_DIR / account_id / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # Save memo
    memo_path = version_dir / "account_memo.json"
    with open(memo_path, "w") as f:
        json.dump(memo, f, indent=2)
    print(f"  ✓ Saved {memo_path}")

    # Save agent spec if provided
    if agent_spec:
        spec_path = version_dir / "agent_spec.json"
        with open(spec_path, "w") as f:
            json.dump(agent_spec, f, indent=2)
        print(f"  ✓ Saved {spec_path}")

    # Save changelog if provided
    if changelog:
        cl_path = version_dir / "changelog.json"
        with open(cl_path, "w") as f:
            json.dump(changelog, f, indent=2)
        print(f"  ✓ Saved {cl_path}")

        # Also save human-readable changelog
        cl_md_path = version_dir / "changelog.md"
        with open(cl_md_path, "w") as f:
            f.write(f"# Changelog: {account_id} v1 → v2\n\n")
            f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write("| Field | Old Value | New Value | Reason |\n")
            f.write("|-------|-----------|-----------|--------|\n")
            for entry in changelog:
                f.write(f"| `{entry.get('field','')}` | {entry.get('old_value','')} | {entry.get('new_value','')} | {entry.get('reason','')} |\n")
        print(f"  ✓ Saved {cl_md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Pipeline: Extract Account Memo")
    parser.add_argument("--transcript", required=True, help="Path to transcript file")
    parser.add_argument("--pipeline", choices=["A", "B"], default="A", help="Pipeline A (v1) or B (v2 patch)")
    parser.add_argument("--source-type", default="onboarding_call", help="demo_call | onboarding_call | onboarding_form")
    parser.add_argument("--v1-memo", help="Path to existing v1 account_memo.json (required for Pipeline B)")
    args = parser.parse_args()

    if args.pipeline == "A":
        memo = run_pipeline_a(args.transcript, args.source_type)
        account_id = memo["account_id"]
        print(f"\n[Result] Account ID: {account_id}")
        save_outputs(account_id, "v1", memo)
        print(f"\n✅ Pipeline A complete for: {account_id}")

    elif args.pipeline == "B":
        if not args.v1_memo:
            print("ERROR: --v1-memo required for Pipeline B")
            sys.exit(1)
        with open(args.v1_memo) as f:
            v1_memo = json.load(f)
        v2_memo, changelog = run_pipeline_b(args.transcript, v1_memo, args.source_type)
        account_id = v2_memo.get("account_id", v1_memo.get("account_id", "unknown"))
        save_outputs(account_id, "v2", v2_memo, changelog=changelog)
        print(f"\n✅ Pipeline B complete for: {account_id}")
