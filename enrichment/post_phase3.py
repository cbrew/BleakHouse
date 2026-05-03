"""Phase 4: Post-generation outputs (manifest + report.html).

Called by all three pipeline entry points after Phase 3 writes
phase3_episode.json. Generates:
  - manifest.json  (passage backlinks for the webapp reader)
  - report.html  (self-contained dark-themed report with passage reveals)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_post_phase3(run_dir: Path, run_id: str) -> None:
    """Generate manifest.json and report.html for a completed run."""
    episode_path = run_dir / "phase3_episode.json"
    if not episode_path.exists():
        logger.warning("No phase3_episode.json in %s — skipping post-phase3", run_dir)
        return

    with open(episode_path) as f:
        json.load(f)  # validate parseable; consumed via build_manifest

    from webapp.build_manifest import build_manifest

    manifest = build_manifest(run_id, audio=False)
    if manifest is None:
        logger.warning("Manifest generation failed for %s", run_id)
        return

    from webapp.build_report import build_report

    if not build_report(run_id):
        logger.warning("Report HTML generation failed for %s", run_id)
