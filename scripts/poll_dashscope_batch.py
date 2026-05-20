"""One-shot DashScope batch status check.

Reads `manifest.json` from the given probe dir, calls
`client.batches.retrieve(batch_id)` exactly once, persists the full
Batch state to `batch_state.json` (overwriting any prior snapshot —
each call is a fresh receipt), prints one summary line to stdout,
and exits.

Designed to be looped externally — the polling cadence lives in the
caller, not in this script. Example usage from a Monitor:

    until PYTHONUNBUFFERED=1 uv run python scripts/poll_dashscope_batch.py \\
        data/runs/_qwen_plus_batch_enrichment_probe/bleak_house_c6
    do sleep 300; done && uv run python scripts/collect_dashscope_batch_enrichment.py \\
        data/runs/_qwen_plus_batch_enrichment_probe/bleak_house_c6

Each iteration of the until-loop becomes one Monitor event.

Exit code:
    0 — batch is in a terminal state (completed/failed/expired/cancelled)
    1 — batch is still in flight (validating/in_progress/finalizing)
    2 — error before we could even ask DashScope (missing manifest,
        missing key, API call raised)

Tracks BleakHouse-el1j.1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
TERMINAL = {"completed", "failed", "expired", "cancelled"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("probe_dir", type=Path,
                   help="Directory containing manifest.json from the submitter")
    args = p.parse_args()

    probe_dir: Path = args.probe_dir
    manifest_path = probe_dir / "manifest.json"
    state_path = probe_dir / "batch_state.json"

    if not manifest_path.exists():
        print(f"ERROR: no manifest at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())
    batch_id = manifest["batch_id"]

    load_dotenv()
    key = os.environ.get("ALIBABA_API_KEY")
    if not key:
        print("ERROR: ALIBABA_API_KEY not set in env / .env", file=sys.stderr)
        return 2

    client = OpenAI(api_key=key, base_url=BASE_URL,
                    timeout=60.0, max_retries=0)
    try:
        batch = client.batches.retrieve(batch_id)
    except Exception as e:
        print(f"ERROR: batches.retrieve({batch_id}) raised: {e}", file=sys.stderr)
        return 2

    state = batch.model_dump(mode="json")
    polled_at = datetime.now(timezone.utc).isoformat()
    state["_polled_at"] = polled_at
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, default=str))

    counts = batch.request_counts
    counts_str = ""
    if counts is not None:
        counts_str = (
            f" counts={counts.completed}/{counts.total} "
            f"(failed={counts.failed})"
        )

    is_terminal = batch.status in TERMINAL
    terminal_flag = "TERMINAL" if is_terminal else "in-flight"
    print(
        f"{polled_at} {terminal_flag} batch_id={batch_id} "
        f"status={batch.status}{counts_str}"
    )
    return 0 if is_terminal else 1


if __name__ == "__main__":
    sys.exit(main())
