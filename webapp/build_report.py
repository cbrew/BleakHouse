"""Generate static report.html files with passage backlinks.

Reads a run's manifest.json and produces a self-contained HTML file with
expandable passage reveals, match quality badges, and enrichment metadata.

Usage:
    uv run python -m webapp.build_report --run ext_v01_baseline_hostprep
    uv run python -m webapp.build_report --all
"""

from __future__ import annotations

import argparse
import json
import logging
from html import escape
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load_manifest(run_dir: Path) -> dict | None:
    """Load manifest from either run_dir/manifest.json or run_dir/audio/manifest.json."""
    for path in [run_dir / "manifest.json", run_dir / "audio" / "manifest.json"]:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def _match_badge(utt: dict) -> str:
    """Render match quality badge for ungrounded utterances."""
    cat = utt.get("match_category", "")
    ratio = utt.get("match_ratio", 0)
    pct = round(ratio * 100)
    if cat == "verified":
        return f'<span class="badge verified">Verified ({pct}%)</span>'
    elif cat == "paraphrase":
        return f'<span class="badge paraphrase">Paraphrase ({pct}%)</span>'
    elif cat == "confabulation":
        return f'<span class="badge confabulation">Confabulation ({pct}%)</span>'
    return ""


def _passage_reveal(ref: str, passages: dict, is_ungrounded: bool) -> str:
    """Build a <details> passage reveal for a passage ref."""
    p = passages.get(ref)
    if not p:
        return ""

    chapter_id = p.get("chapter_id", "")
    chapter_num = chapter_id.lstrip("c") if chapter_id.startswith("c") else chapter_id
    chapter_html = f'<div class="pr-chapter">Chapter {escape(chapter_num)}</div>' if chapter_num else ""

    text_html = f'<div class="pr-text">{escape(p.get("text", ""))}</div>'
    summary = p.get("summary", "")
    summary_html = f'<div class="pr-summary">{escape(summary)}</div>' if summary else ""

    # Match badge for ungrounded passages
    badge = ""
    if is_ungrounded and p.get("match_category"):
        cat = p["match_category"]
        pct = round(p.get("match_ratio", 0) * 100)
        if cat == "verified":
            badge = f'<span class="badge verified">Verified quote ({pct}% match)</span>'
        elif cat == "paraphrase":
            badge = f'<span class="badge paraphrase">Likely paraphrase ({pct}% match)</span>'
        elif cat == "confabulation":
            badge = f'<span class="badge confabulation">Probable confabulation ({pct}% match)</span>'
    elif is_ungrounded and p.get("suggested"):
        badge = '<span class="badge suggested">Suggested passage (not a direct source)</span>'

    # Metadata chips
    chips = []
    for char in p.get("characters_present", []):
        chips.append(f'<span class="chip char">{escape(char)}</span>')
    for theme in p.get("themes", []):
        chips.append(f'<span class="chip theme">{escape(theme)}</span>')
    for emo in p.get("emotional_register", []):
        chips.append(f'<span class="chip emo">{escape(emo)}</span>')
    meta_html = f'<div class="pr-meta">{"".join(chips)}</div>' if chips else ""

    label = f"[{ref}]" if not chapter_num else f"Chapter {chapter_num}, {ref}"

    return (
        f'<details class="pr">'
        f'<summary>{escape(label)}</summary>'
        f'{badge}{chapter_html}{text_html}{summary_html}{meta_html}'
        f'</details>'
    )


def build_report_html(manifest: dict) -> str:
    """Generate a self-contained HTML report from a manifest."""
    run_id = manifest.get("run_id", "unknown")
    title = manifest.get("title", "")
    experts = manifest.get("experts", [])
    segments = manifest.get("segments", [])
    passages = manifest.get("passages", {})
    passage_source = manifest.get("passage_source", "grounded")
    is_ungrounded = passage_source == "ungrounded"

    # Count stats
    total_words = 0
    total_turns = 0
    total_quotes = 0
    for seg in segments:
        for turn in seg.get("turns", []):
            total_turns += 1
            for utt in turn.get("utterances", []):
                total_words += len(utt.get("text", "").split())
                if utt.get("is_quote") or utt.get("quote_mode") == "reading":
                    total_quotes += 1

    # Build expert intro
    expert_names = ", ".join(e["name"] for e in experts)

    # Build body
    body_parts = []
    for seg in segments:
        seg_title = seg.get("title", "Untitled")
        seg_type = seg.get("segment_type", "")
        body_parts.append(f'<h2 class="seg-title">{escape(seg_title)} <span class="seg-type">({escape(seg_type)})</span></h2>')

        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "")
            role = turn.get("role", "")
            speaker_cls = "host" if speaker == "Host" else "expert"

            # Collect passage refs for this turn
            turn_refs = []
            seen = set()
            for utt in turn.get("utterances", []):
                ref = utt.get("passage_ref", "")
                if ref and ref not in seen:
                    seen.add(ref)
                    turn_refs.append(ref)

            # Build utterance HTML
            utt_parts = []
            for utt in turn.get("utterances", []):
                text = utt.get("text", "")
                is_quote = utt.get("is_quote", False)
                quote_mode = utt.get("quote_mode", "none")

                if is_quote or quote_mode == "reading":
                    utt_parts.append(f'<span class="quote">{escape(text)}</span>')
                    badge = _match_badge(utt)
                    if badge:
                        utt_parts.append(f' {badge}')
                elif quote_mode == "setup":
                    utt_parts.append(f'<span class="setup">{escape(text)}</span>')
                elif quote_mode == "commentary":
                    utt_parts.append(f'<span class="commentary">{escape(text)}</span>')
                else:
                    utt_parts.append(f'<span>{escape(text)}</span>')
                utt_parts.append(" ")

            # Build passage reveals
            reveals = []
            for ref in turn_refs:
                reveal = _passage_reveal(ref, passages, is_ungrounded)
                if reveal:
                    reveals.append(reveal)

            body_parts.append(
                f'<div class="turn">'
                f'<div class="speaker {speaker_cls}">{escape(speaker)}'
                f'{"" if not role else f" <span class=role>({escape(role)})</span>"}'
                f'</div>'
                f'<div class="speech">{"".join(utt_parts)}</div>'
                f'{"".join(reveals)}'
                f'</div>'
            )

    source_label = "No passages (prior knowledge)" if is_ungrounded else f"Passage-grounded ({passage_source})"

    return _TEMPLATE.format(
        title=escape(title),
        run_id=escape(run_id),
        expert_names=escape(expert_names),
        n_segments=len(segments),
        total_words=total_words,
        total_turns=total_turns,
        total_quotes=total_quotes,
        n_passages=len(passages),
        source_label=escape(source_label),
        body="".join(body_parts),
    )


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} — {run_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: Georgia, "Times New Roman", serif;
    max-width: 800px; margin: 2em auto; padding: 0 1em;
    color: #1a1a1a; background: #fafaf8; line-height: 1.6;
}}
header {{ margin-bottom: 2em; border-bottom: 2px solid #2c3e50; padding-bottom: 1em; }}
h1 {{ font-size: 1.5em; color: #2c3e50; margin-bottom: 0.2em; }}
.meta {{ color: #666; font-size: 0.85em; }}
.meta span {{ margin-right: 1.5em; }}
h2.seg-title {{
    font-size: 1.15em; color: #2c3e50; margin: 1.8em 0 0.8em;
    border-bottom: 1px solid #ddd; padding-bottom: 0.3em;
}}
.seg-type {{ color: #888; font-weight: normal; font-size: 0.85em; }}
.turn {{ margin-bottom: 1.2em; }}
.speaker {{
    font-weight: 700; font-size: 0.9em; margin-bottom: 0.2em;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
}}
.speaker.host {{ color: #2c3e50; }}
.speaker.expert {{ color: #8b4513; }}
.role {{ color: #888; font-weight: normal; font-size: 0.85em; }}
.speech {{ font-size: 0.95em; }}
.quote {{
    display: inline;
    font-style: italic; color: #4a2c0a;
    border-left: 3px solid #c9a96e; padding-left: 0.5em;
}}
.setup {{ color: #555; }}
.commentary {{ color: #333; }}
/* Passage reveals */
details.pr {{
    margin: 0.4em 0 0.4em 1em;
    border: 1px solid #ddd; border-radius: 4px;
    font-size: 0.85em; background: #fff;
}}
details.pr summary {{
    cursor: pointer; padding: 0.3em 0.6em;
    color: #2c6fbb; font-family: monospace; font-size: 0.9em;
}}
details.pr summary:hover {{ background: #f0f4f8; }}
details.pr[open] {{ padding: 0.4em 0.6em; }}
.pr-chapter {{ font-weight: 600; color: #2c3e50; margin-bottom: 0.3em; }}
.pr-text {{
    font-size: 0.9em; color: #333; margin: 0.3em 0;
    max-height: 200px; overflow-y: auto;
    border-left: 2px solid #e0d8c8; padding-left: 0.6em;
}}
.pr-summary {{ color: #555; font-style: italic; margin: 0.3em 0; }}
.pr-meta {{ margin-top: 0.3em; }}
.chip {{
    display: inline-block; padding: 1px 6px; margin: 2px;
    border-radius: 10px; font-size: 0.8em;
}}
.chip.char {{ background: #e8f4fd; color: #1a5276; }}
.chip.theme {{ background: #fef9e7; color: #7d6608; }}
.chip.emo {{ background: #fdedec; color: #922b21; }}
/* Match badges */
.badge {{
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 0.75em; font-weight: 600; vertical-align: middle;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}}
.badge.verified {{ background: #d4edda; color: #155724; }}
.badge.paraphrase {{ background: #fff3cd; color: #856404; }}
.badge.confabulation {{ background: #f8d7da; color: #721c24; }}
.badge.suggested {{ background: #e2e3e5; color: #383d41; }}
footer {{
    margin-top: 2em; padding-top: 1em; border-top: 1px solid #ddd;
    color: #888; font-size: 0.8em;
}}
</style>
</head>
<body>
<header>
    <h1>{title}</h1>
    <div class="meta">
        <span>Run: <strong>{run_id}</strong></span>
        <span>Experts: {expert_names}</span>
    </div>
    <div class="meta">
        <span>{n_segments} segments</span>
        <span>{total_words:,} words</span>
        <span>{total_turns} turns</span>
        <span>{total_quotes} quotes</span>
        <span>{n_passages} passages referenced</span>
        <span>{source_label}</span>
    </div>
</header>
{body}
<footer>
    Generated from run <code>{run_id}</code>. Passage reveals expand on click.
</footer>
</body>
</html>"""


def build_report(run_id: str) -> bool:
    """Build report.html for a single run. Returns True on success."""
    run_dir = DATA_DIR / "runs" / run_id
    manifest = _load_manifest(run_dir)
    if manifest is None:
        logger.warning("No manifest for run %s — run build_manifest first", run_id)
        return False

    html = build_report_html(manifest)
    out_path = run_dir / "report.html"
    out_path.write_text(html)
    logger.info("Wrote %s (%d bytes)", out_path.name, len(html))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static report.html with passage reveals")
    parser.add_argument("--run", help="Run ID")
    parser.add_argument("--all", action="store_true", help="All runs with manifests")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    if args.all:
        runs_dir = DATA_DIR / "runs"
        count = 0
        for run_dir in sorted(runs_dir.iterdir()):
            if _load_manifest(run_dir) is not None:
                if build_report(run_dir.name):
                    count += 1
        logger.info("Generated %d report.html files", count)
    elif args.run:
        build_report(args.run)
    else:
        parser.error("Specify --run or --all")


if __name__ == "__main__":
    main()
