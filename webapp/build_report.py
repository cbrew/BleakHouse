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
    elif cat == "distant_echo":
        return f'<span class="badge distant-echo">Distant echo ({pct}%) — loosest thematic connection</span>'
    elif cat == "no_clear_source":
        return f'<span class="badge no-source">No clear source ({pct}%) — nearest passage shown</span>'
    elif cat == "invented":
        autopsy = utt.get("autopsy")
        if autopsy:
            pct_in = autopsy.get("pct_in_novel", 0)
            return (f'<span class="badge invented">Invented — '
                    f'{pct_in}% of words appear in the novel</span>')
        return '<span class="badge invented">Invented — no match found</span>'
    return ""


def _autopsy_html(utt: dict) -> str:
    """Render confabulation autopsy detail for invented quotes."""
    autopsy = utt.get("autopsy")
    if not autopsy:
        return ""

    quote_words = autopsy.get("quote_words", 0)
    in_novel = autopsy.get("words_in_novel", 0)
    absent = autopsy.get("words_absent", 0)
    pct = autopsy.get("pct_in_novel", 0)
    distinctive = autopsy.get("distinctive_absent", [])

    parts = ['<div class="autopsy">']
    parts.append(f'<div class="autopsy-stat">Of {quote_words} unique words, '
                 f'{in_novel} ({pct}%) appear somewhere in the novel, '
                 f'{absent} do not.</div>')
    if distinctive:
        words_html = ", ".join(f"<code>{escape(w)}</code>" for w in distinctive)
        parts.append(f'<div class="autopsy-absent">Distinctive absent words: {words_html}</div>')

    reason = autopsy.get("fallback_reason", "")
    shared = autopsy.get("shared_words", 0)
    if reason == "word_overlap":
        parts.append(f'<div class="autopsy-fallback">Nearest passage selected by word overlap '
                     f'({shared} shared words).</div>')

    parts.append('</div>')
    return "".join(parts)


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
        elif cat == "distant_echo":
            badge = f'<span class="badge distant-echo">Distant echo ({pct}% match)</span>'
        elif cat == "no_clear_source":
            badge = f'<span class="badge no-source">No clear source ({pct}% match)</span>'
        elif cat == "invented":
            badge = '<span class="badge invented">Nearest passage by word overlap</span>'
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


def _host_prep_html(brief: dict | None, interviews: list[dict] | None, passages: dict) -> str:
    """Render host preparation data (pre-interviews + brief) for a segment."""
    if not brief and not interviews:
        return ""

    parts = ['<details class="hp-section">',
             '<summary>Host preparation</summary>']

    # Pre-interviews
    if interviews:
        parts.append('<div class="hp-interviews">')
        parts.append('<h4>Pre-interviews</h4>')
        for iv in interviews:
            name = iv.get("expert_name", "Expert")
            parts.append('<details class="hp-interview">')
            parts.append(f'<summary>{escape(name)}</summary>')

            strongest = iv.get("strongest_take", "")
            if strongest:
                parts.append(f'<div class="hp-strongest">{escape(strongest)}</div>')

            kp = iv.get("key_points", [])
            if kp:
                parts.append('<div class="hp-label">Key points:</div><ul>')
                for point in kp:
                    parts.append(f'<li>{escape(point)}</li>')
                parts.append('</ul>')

            quotes = iv.get("potential_quotes", [])
            if quotes:
                parts.append('<div class="hp-label">Passages they want to quote:</div><ul>')
                for q in quotes:
                    parts.append(f'<li class="hp-quote">{escape(q)}</li>')
                parts.append('</ul>')

            angles = iv.get("disagreement_angles", [])
            if angles:
                parts.append('<div class="hp-label">Disagreement angles:</div><ul>')
                for a in angles:
                    parts.append(f'<li class="hp-disagree">{escape(a)}</li>')
                parts.append('</ul>')

            parts.append('</details>')
        parts.append('</div>')

    # Brief (questions + steering)
    if brief:
        questions = brief.get("questions", [])
        if questions:
            parts.append('<div class="hp-questions">')
            parts.append('<h4>Planned questions</h4>')
            for q in questions:
                target = q.get("target_expert", "")
                question = q.get("question", "")
                intent = q.get("intent", "")
                follow = q.get("follow_up_for", [])
                parts.append('<div class="hp-q">')
                parts.append(f'<div class="hp-q-target">{escape(target)}</div>')
                parts.append(f'<div class="hp-q-text">{escape(question)}</div>')
                if intent:
                    parts.append(f'<div class="hp-q-intent">{escape(intent)}</div>')
                if follow:
                    names = ", ".join(follow) if isinstance(follow, list) else str(follow)
                    parts.append(f'<div class="hp-q-follow">Follow up: {escape(names)}</div>')
                parts.append('</div>')
            parts.append('</div>')

        steering = brief.get("steering_notes", "")
        if steering:
            parts.append(f'<div class="hp-steering"><h4>Steering notes</h4>{escape(steering)}</div>')

        cross = brief.get("cross_engagement_targets", [])
        if cross:
            parts.append('<div class="hp-cross"><h4>Cross-engagement targets</h4><ul>')
            for c in cross:
                parts.append(f'<li>{escape(c)}</li>')
            parts.append('</ul></div>')

    parts.append('</details>')
    return "\n".join(parts)


def build_report_html(manifest: dict) -> str:
    """Generate a self-contained HTML report from a manifest."""
    run_id = manifest.get("run_id", "unknown")
    title = manifest.get("title", "")
    experts = manifest.get("experts", [])
    segments = manifest.get("segments", [])
    passages = manifest.get("passages", {})
    passage_source = manifest.get("passage_source", "grounded")
    is_ungrounded = passage_source == "ungrounded"
    host_prep = manifest.get("host_prep")

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

    # Index host prep data by segment
    briefs_by_seg: list[dict | None] = [None] * len(segments)
    interviews_by_seg: list[list[dict] | None] = [None] * len(segments)
    if host_prep:
        for si, brief in enumerate(host_prep.get("briefs") or []):
            if si < len(segments):
                briefs_by_seg[si] = brief
        for si, ivs in enumerate(host_prep.get("interviews") or []):
            if si < len(segments):
                interviews_by_seg[si] = ivs

    # Build body
    body_parts = []
    for seg_idx, seg in enumerate(segments):
        seg_title = seg.get("title", "Untitled")
        seg_type = seg.get("segment_type", "")
        body_parts.append(f'<h2 class="seg-title">{escape(seg_title)} <span class="seg-type">({escape(seg_type)})</span></h2>')

        # Host preparation section (collapsible)
        hp_html = _host_prep_html(briefs_by_seg[seg_idx], interviews_by_seg[seg_idx], passages)
        if hp_html:
            body_parts.append(hp_html)

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
                    autopsy_detail = _autopsy_html(utt)
                    if autopsy_detail:
                        utt_parts.append(autopsy_detail)
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

    # Reading list section
    reading_list = (host_prep or {}).get("reading_list")
    if reading_list:
        verified = reading_list.get("verified", [])
        unverified = reading_list.get("unverified", [])
        rate = reading_list.get("verification_rate", 0)
        body_parts.append(
            '<h2 class="seg-title">Reading List '
            f'<span class="seg-type">({len(verified)} verified, '
            f'{len(unverified)} unverified, {rate:.0%} rate)</span></h2>'
        )
        if verified:
            body_parts.append('<div class="reading-list"><h3>Verified references</h3><ul>')
            for ref in verified:
                source = ref.get("verification_source", "")
                expert = ref.get("expert_name", "")
                raw = ref.get("raw_text", "")
                oa_title = ref.get("openalex_title", "")
                cited = ref.get("openalex_cited_by", 0)
                label = f"{escape(raw)}"
                if oa_title and oa_title != raw:
                    label += f' <span class="seg-type">[{escape(oa_title)}]</span>'
                if cited:
                    label += f' <span class="seg-type">(cited {cited}×)</span>'
                body_parts.append(
                    f'<li>{label} — <em>{escape(expert)}</em> '
                    f'<span class="match-badge">{escape(source)}</span></li>'
                )
            body_parts.append('</ul></div>')
        if unverified:
            body_parts.append('<div class="reading-list"><h3>Unverified references</h3><ul>')
            for ref in unverified:
                expert = ref.get("expert_name", "")
                raw = ref.get("raw_text", "")
                body_parts.append(f'<li>{escape(raw)} — <em>{escape(expert)}</em></li>')
            body_parts.append('</ul></div>')

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
:root {{
    --bg: #1a1a2e;
    --surface: #16213e;
    --surface-alt: #0f3460;
    --text: #e8e8e8;
    --text-dim: #8888aa;
    --accent: #e94560;
    --passage-warm: #d4c5a0;
    --passage-bg: #1e1a14;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: Georgia, "Times New Roman", serif;
    max-width: 800px; margin: 0 auto; padding: 2em 1em;
    color: var(--text); background: var(--bg); line-height: 1.6;
}}
.report-nav {{
    margin-bottom: 1.5em; padding-bottom: 0.8em;
    border-bottom: 1px solid var(--surface-alt);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
    font-size: 0.85em;
}}
.report-nav a {{ color: var(--text-dim); text-decoration: none; }}
.report-nav a:hover {{ color: var(--accent); }}
.report-nav .sep {{ color: var(--surface-alt); margin: 0 0.5em; }}
header {{
    margin-bottom: 2em; border-bottom: 2px solid var(--surface-alt);
    padding-bottom: 1em;
}}
h1 {{ font-size: 1.5em; color: var(--accent); margin-bottom: 0.2em; }}
.meta {{ color: var(--text-dim); font-size: 0.85em; }}
.meta span {{ margin-right: 1.5em; }}
h2.seg-title {{
    font-size: 1.15em; color: var(--accent); margin: 1.8em 0 0.8em;
    border-bottom: 1px solid var(--surface-alt); padding-bottom: 0.3em;
}}
.seg-type {{ color: var(--text-dim); font-weight: normal; font-size: 0.85em; }}
.turn {{ margin-bottom: 1.2em; }}
.speaker {{
    font-weight: 700; font-size: 0.9em; margin-bottom: 0.2em;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
}}
.speaker.host {{ color: var(--accent); }}
.speaker.expert {{ color: var(--passage-warm); }}
.role {{ color: var(--text-dim); font-weight: normal; font-size: 0.85em; }}
.speech {{ font-size: 0.95em; color: var(--text); }}
.quote {{
    display: inline;
    font-style: italic; color: var(--passage-warm);
    border-left: 3px solid #c9a96e; padding-left: 0.5em;
}}
.setup {{ color: var(--text-dim); }}
.commentary {{ color: #ccc; }}
/* Passage reveals */
details.pr {{
    margin: 0.4em 0 0.4em 1em;
    border: 1px solid var(--surface-alt); border-radius: 4px;
    font-size: 0.85em; background: var(--surface);
}}
details.pr summary {{
    cursor: pointer; padding: 0.3em 0.6em;
    color: #6fa8dc; font-family: monospace; font-size: 0.9em;
}}
details.pr summary:hover {{ background: var(--surface-alt); }}
details.pr[open] {{ padding: 0.4em 0.6em; }}
.pr-chapter {{ font-weight: 600; color: var(--accent); margin-bottom: 0.3em; }}
.pr-text {{
    font-size: 0.9em; color: #ccc; margin: 0.3em 0;
    max-height: 200px; overflow-y: auto;
    border-left: 2px solid var(--passage-warm); padding-left: 0.6em;
}}
.pr-summary {{ color: var(--text-dim); font-style: italic; margin: 0.3em 0; }}
.pr-meta {{ margin-top: 0.3em; }}
.chip {{
    display: inline-block; padding: 1px 6px; margin: 2px;
    border-radius: 10px; font-size: 0.8em;
}}
.chip.char {{ background: #1a3a5c; color: #8fc4e8; }}
.chip.theme {{ background: #3d3510; color: #d4c060; }}
.chip.emo {{ background: #3d1515; color: #e88; }}
/* Match badges */
.badge {{
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 0.75em; font-weight: 600; vertical-align: middle;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}}
.badge.verified {{ background: #1e4620; color: #6fdc6f; }}
.badge.paraphrase {{ background: #4a3f10; color: #e8d44d; }}
.badge.distant-echo {{ background: #4a2a10; color: #e8a44d; }}
.badge.no-source {{ background: #4a1a1a; color: #e87070; }}
.badge.invented {{ background: #e94560; color: #fff; }}
.badge.suggested {{ background: var(--surface-alt); color: var(--text-dim); }}
/* Autopsy */
.autopsy {{
    margin: 0.3em 0 0.3em 1em; padding: 0.4em 0.6em;
    background: var(--passage-bg); border-left: 3px solid var(--accent);
    font-size: 0.82em; color: var(--text-dim);
}}
.autopsy-stat {{ margin-bottom: 0.2em; }}
.autopsy-absent {{ color: #e87070; }}
.autopsy-absent code {{ background: #3d1515; padding: 1px 4px; border-radius: 2px; font-size: 0.9em; color: #e87070; }}
.autopsy-fallback {{ color: var(--text-dim); font-style: italic; margin-top: 0.2em; }}
/* Host preparation */
details.hp-section {{
    margin: 0.5em 0 1em; border: 1px solid var(--surface-alt);
    border-radius: 6px; background: var(--surface); font-size: 0.88em;
}}
details.hp-section summary {{
    cursor: pointer; padding: 0.5em 0.8em; color: #6fa8dc;
    font-weight: 600; font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}}
details.hp-section summary:hover {{ background: var(--surface-alt); }}
details.hp-section[open] {{ padding: 0.5em 0.8em; }}
details.hp-section h4 {{ color: var(--accent); font-size: 0.95em; margin: 0.6em 0 0.3em; }}
details.hp-interview {{
    margin: 0.3em 0; border-left: 2px solid var(--passage-warm);
    padding-left: 0.6em;
}}
details.hp-interview summary {{ cursor: pointer; color: var(--passage-warm); font-weight: 600; padding: 0.2em 0; }}
.hp-strongest {{ color: var(--text); font-style: italic; margin: 0.3em 0; }}
.hp-label {{ color: var(--text-dim); font-weight: 600; margin-top: 0.4em; font-size: 0.9em; }}
.hp-quote {{ color: var(--passage-warm); font-style: italic; }}
.hp-disagree {{ color: #e87070; }}
.hp-questions {{ margin-top: 0.5em; }}
.hp-q {{ margin: 0.5em 0; padding: 0.4em; border-left: 2px solid #6fa8dc; padding-left: 0.6em; }}
.hp-q-target {{ color: var(--accent); font-weight: 600; font-size: 0.9em; }}
.hp-q-text {{ color: var(--text); }}
.hp-q-intent {{ color: var(--text-dim); font-style: italic; font-size: 0.9em; margin-top: 0.2em; }}
.hp-q-follow {{ color: var(--text-dim); font-size: 0.85em; }}
.hp-steering {{ margin-top: 0.5em; color: var(--text-dim); line-height: 1.5; }}
.hp-cross {{ margin-top: 0.5em; }}
.hp-cross li {{ color: var(--text-dim); margin: 0.3em 0; }}
footer {{
    margin-top: 2em; padding-top: 1em; border-top: 1px solid var(--surface-alt);
    color: var(--text-dim); font-size: 0.8em;
}}
</style>
</head>
<body>
<nav class="report-nav">
    <a href="/tracker">← Back to matrix</a>
    <span class="sep">·</span>
    <a href="/player?run={run_id}">♫ Listen</a>
    <span class="sep">·</span>
    <a href="/prep?run={run_id}">📄 Host prep</a>
</nav>
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
