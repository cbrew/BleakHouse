"""Shared data loading utilities for cross-novel analysis.

Parses the cross-novel run naming convention and loads episode data,
assignments, and per-novel source texts.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPTS_DIR.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
NOVELS_DIR = BASE_DIR / "data" / "novels"

# Novel keys and their run-name prefixes
NOVEL_PREFIXES = {
    "omf": "our_mutual_friend",
    "motf": "mill_on_the_floss",
    "nas": "north_and_south",
    "pti": "passage_to_india",
}

NOVEL_TITLES = {
    "our_mutual_friend": "Our Mutual Friend",
    "mill_on_the_floss": "The Mill on the Floss",
    "north_and_south": "North and South",
    "passage_to_india": "A Passage to India",
}

COND_PREFIXES = {
    "trn": "transport",
    "emb": "embedding",
    "nop": "no_passages",
}

PANEL_IDS = [
    "v01_baseline",
    "v11_rosen_blackstone_woodcourt",
    "v21_hartley_blackstone_edmund",
    "v22_hartley_blackstone_rosen",
    "v23_hartley_rosen_woodcourt",
    "v26_blackstone_woodcourt_edmund",
    "v29_rosen_blackstone_trevelyan",
    "v30_woodcourt_edmund_trevelyan",
]

ALL_EXPERTS = {
    "Eleanor Hartley", "James Blackstone", "Caroline Woodcourt",
    "Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan",
    "Host",
}

PROVISION_DIMS = [
    "prov_character_development", "prov_plot_advancement",
    "prov_thematic_depth", "prov_social_critique",
    "prov_humor_entertainment", "prov_atmosphere_setting",
    "prov_narrative_technique",
]


def parse_run_name(dirname: str) -> tuple[str, str, str] | None:
    """Parse a cross-novel run directory name.

    Returns (novel_key, condition, panel_id) or None if not parseable.
    """
    for npfx, novel_key in NOVEL_PREFIXES.items():
        for cpfx, condition in COND_PREFIXES.items():
            prefix = f"{npfx}_{cpfx}_"
            if dirname.startswith(prefix):
                panel_id = dirname[len(prefix):]
                if panel_id in PANEL_IDS:
                    return novel_key, condition, panel_id
    return None


def discover_runs() -> dict[tuple[str, str, str], Path]:
    """Discover all cross-novel runs.

    Returns dict of (novel_key, condition, panel_id) -> run_dir_path.
    Only includes runs with phase3_episode.json.
    """
    runs = {}
    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        result = parse_run_name(d.name)
        if result and (d / "phase3_episode.json").exists():
            runs[result] = d
    return runs


def load_episode(run_dir: Path) -> dict:
    return json.loads((run_dir / "phase3_episode.json").read_text())


def load_assignments(run_dir: Path) -> list[dict]:
    path = run_dir / "phase1_assignments.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("assignments", data if isinstance(data, list) else [])


def extract_turns(episode: dict) -> list[dict]:
    """Extract all turns with speaker and concatenated text."""
    turns = []
    for seg in episode.get("segments", []):
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "Unknown")
            utterances = turn.get("utterances", [])
            texts = [u["text"] for u in utterances if "text" in u]
            full_text = " ".join(texts)
            quote_count = sum(1 for u in utterances if u.get("is_quote", False))
            turns.append({
                "speaker": speaker,
                "role": turn.get("role", ""),
                "text": full_text,
                "quote_count": quote_count,
                "utterance_count": len(utterances),
                "word_count": len(full_text.split()),
            })
    return turns


def load_novel_characters(novel_key: str) -> list[str]:
    """Build character list from enrichment data for a novel."""
    path = NOVELS_DIR / novel_key / "passages_enriched.json"
    if not path.exists():
        return []
    passages = json.loads(path.read_text())
    char_counts: Counter[str] = Counter()
    for p in passages:
        for c in p.get("enrichment", {}).get("characters_present", []):
            char_counts[c] += 1
    # Return characters appearing in >= 10 passages
    return [c for c, n in char_counts.most_common() if n >= 10]


def build_char_patterns(characters: list[str]) -> dict[str, re.Pattern]:
    return {
        name: re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
        for name in characters
    }


def count_characters(text: str, patterns: dict[str, re.Pattern]) -> Counter:
    counts = Counter()
    for name, pattern in patterns.items():
        n = len(pattern.findall(text))
        if n > 0:
            counts[name] = n
    return counts


def shannon_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


STOP_WORDS = set("""
a an the and or but in on at to for of is it that this was were be been
being have has had do does did will would shall should may might can could
not no nor so if then than too very just about above after again all also
am are as because before between both by down during each few from further
get got he her here hers herself him himself his how i its itself
let like me more most my myself now off only other our ours ourselves out
own re s same she some such t their theirs them themselves there these they
through under until up us we what when where which while who whom why
with you your yours yourself yourselves d ll m o ve wasn t don doesn didn
couldn wouldn shouldn isn aren haven hasn hadn mustn needn shan won
about actually already always another any anything back came come could
course day didn different doing done enough even every everything fact
find first found going good got great had has have here him how into
its just keep kind know last left let life like little long look made
make man many may me might mind more most much must my never new next
nothing now off often oh old one only or other our out over own part
people place point put quite rather read real really right said same
say see seem she should show since small some something sometimes still
such take tell than that the their them then there these they thing think
this those though thought three through time too two under up us use
used using very want was way we well went were what when where which
while who why will with without work world would year yet you your
much well think know really going want right thing way make things
""".split())


def get_vocab_words(text: str) -> list[str]:
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]
