#!/usr/bin/env python3
"""
Batch runner: processes all transcripts in a dataset folder.
Pairs demo + onboarding transcripts by account name convention.
Runs Pipeline A then Pipeline B per account.

Usage:
  python batch_run.py --dataset ./data
  python batch_run.py --dataset ./data --account bens-electric-solutions
"""

import json
import os
import sys
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timezone

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_memo import run_pipeline_a, run_pipeline_b, save_outputs
from generate_agent_spec import generate_agent_spec, save_agent_spec

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
SUMMARY_PATH = Path(__file__).parent.parent / "outputs" / "batch_summary.json"


def find_transcript_pairs(dataset_dir: Path) -> list[dict]:
    """
    Discover transcript pairs in dataset directory.
    Naming convention:
      demo_<account_slug>.docx / demo_<account_slug>.txt
      onboarding_<account_slug>.docx / onboarding_<account_slug>.txt
    Or a single file named <account_slug>.docx is treated as onboarding only.
    """
    pairs = {}
    supported = {".txt", ".docx", ".md"}

    for f in dataset_dir.iterdir():
        if f.suffix not in supported:
            continue
        name = f.stem.lower()
        if name.startswith("demo_"):
            slug = name[5:]
            pairs.setdefault(slug, {})["demo"] = f
        elif name.startswith("onboarding_"):
            slug = name[11:]
            pairs.setdefault(slug, {})["onboarding"] = f
        else:
            # Treat as onboarding-only
            pairs.setdefault(name, {})["onboarding"] = f

    return [{"slug": k, **v} for k, v in pairs.items()]


def process_account(slug: str, demo_path: Path = None, onboarding_path: Path = None) -> dict:
    """Run full pipeline for one account. Returns summary dict."""
    result = {
        "slug": slug,
        "status": "pending",
        "account_id": None,
        "v1_generated": False,
        "v2_generated": False,
        "errors": []
    }

    try:
        # ── Pipeline A ─────────────────────────────────────────────────────
        primary_transcript = demo_path or onboarding_path
        source_type = "demo_call" if demo_path else "onboarding_call"

        print(f"\n{'='*60}")
        print(f"  Processing: {slug}")
        print(f"  Source:     {primary_transcript.name} ({source_type})")
        print(f"{'='*60}")

        memo_v1 = run_pipeline_a(str(primary_transcript), source_type)
        account_id = memo_v1.get("account_id", slug)
        result["account_id"] = account_id

        # Generate v1 agent spec
        spec_v1 = generate_agent_spec(memo_v1)

        # Save all v1 artifacts
        save_outputs(account_id, "v1", memo_v1, spec_v1)
        result["v1_generated"] = True

        # ── Pipeline B ─────────────────────────────────────────────────────
        # If we have both demo + onboarding, run B with onboarding
        # If we only have onboarding, we already ran A on it — B is skipped unless
        # an explicit v1 already existed
        if demo_path and onboarding_path:
            print(f"\n  Running Pipeline B with: {onboarding_path.name}")
            memo_v2, changelog = run_pipeline_b(
                str(onboarding_path), memo_v1, "onboarding_call"
            )
            spec_v2 = generate_agent_spec(memo_v2)
            save_outputs(account_id, "v2", memo_v2, spec_v2, changelog)
            result["v2_generated"] = True
        else:
            print(f"  [Info] Only one transcript found — v2 skipped (no pair)")

        result["status"] = "success"
        print(f"\n  ✅ Done: {account_id}")

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        print(f"\n  ❌ Error processing {slug}: {e}")
        traceback.print_exc()

    return result


def save_summary(results: list[dict]):
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "accounts": results
    }
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n📊 Summary saved: {SUMMARY_PATH}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Batch Runner")
    parser.add_argument("--dataset", required=True, help="Path to folder with transcript files")
    parser.add_argument("--account", help="Process only this account slug (optional)")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    if not dataset_dir.exists():
        print(f"ERROR: Dataset directory not found: {dataset_dir}")
        sys.exit(1)

    pairs = find_transcript_pairs(dataset_dir)
    if not pairs:
        print(f"No transcripts found in {dataset_dir}")
        sys.exit(1)

    # Filter to single account if requested
    if args.account:
        pairs = [p for p in pairs if p["slug"] == args.account]
        if not pairs:
            print(f"No transcript found for account: {args.account}")
            sys.exit(1)

    print(f"\n🚀 Clara Batch Pipeline")
    print(f"   Dataset: {dataset_dir}")
    print(f"   Accounts found: {len(pairs)}")

    results = []
    for pair in pairs:
        result = process_account(
            slug=pair["slug"],
            demo_path=pair.get("demo"),
            onboarding_path=pair.get("onboarding")
        )
        results.append(result)

    summary = save_summary(results)

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"  Total:   {summary['total']}")
    print(f"  Success: {summary['success']}")
    print(f"  Errors:  {summary['errors']}")
    print(f"{'='*60}")
