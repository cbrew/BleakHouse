"""Novel-specific enrichment prompts for the generalization study."""

from dataclasses import dataclass


@dataclass
class NovelPromptConfig:
    title: str
    author: str
    year: str
    narration_note: str
    theme_examples: str
    character_note: str


NOVEL_CONFIGS: dict[str, NovelPromptConfig] = {
    "our_mutual_friend": NovelPromptConfig(
        title="Our Mutual Friend",
        author="Charles Dickens",
        year="1865",
        narration_note=(
            "*Our Mutual Friend* uses third-person omniscient narration throughout, "
            "with Dickens' characteristic shifting register — from satirical commentary "
            "to intimate psychological insight."
        ),
        theme_examples=(
            "'money', 'dust', 'death', 'identity', 'class', 'marriage', 'disguise', "
            "'poverty', 'greed', 'redemption', 'waste', 'river', 'education', 'will'"
        ),
        character_note=(
            "Use canonical names (e.g. 'John Harmon' not 'John', 'Bella Wilfer' not "
            "'Bella', 'Silas Wegg' not 'Wegg'). Include characters referenced indirectly."
        ),
    ),
    "mill_on_the_floss": NovelPromptConfig(
        title="The Mill on the Floss",
        author="George Eliot",
        year="1860",
        narration_note=(
            "*The Mill on the Floss* uses third-person omniscient narration with "
            "occasional first-person intrusions from the narrator. Eliot's narrator "
            "is analytical and philosophical, offering commentary on provincial life."
        ),
        theme_examples=(
            "'family', 'education', 'gender', 'class', 'duty', 'desire', 'renunciation', "
            "'memory', 'childhood', 'intelligence', 'religion', 'commerce', 'flood', "
            "'tradition', 'respectability'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Maggie Tulliver' not 'Maggie', 'Tom Tulliver' "
            "not 'Tom', 'Philip Wakem' not 'Philip'). Include characters referenced "
            "indirectly."
        ),
    ),
    "north_and_south": NovelPromptConfig(
        title="North and South",
        author="Elizabeth Gaskell",
        year="1855",
        narration_note=(
            "*North and South* uses third-person narration closely aligned with "
            "Margaret Hale's perspective. The narrative moves between domestic scenes "
            "and industrial settings."
        ),
        theme_examples=(
            "'industry', 'class', 'strikes', 'religion', 'duty', 'north', 'south', "
            "'pride', 'poverty', 'death', 'authority', 'independence', 'labour', "
            "'masters', 'workers', 'gentility'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Margaret Hale' not 'Margaret', 'John Thornton' "
            "not 'Thornton', 'Nicholas Higgins' not 'Higgins'). Include characters "
            "referenced indirectly."
        ),
    ),
    "passage_to_india": NovelPromptConfig(
        title="A Passage to India",
        author="E. M. Forster",
        year="1924",
        narration_note=(
            "*A Passage to India* uses third-person omniscient narration with "
            "Forster's characteristic ironic distance. The novel moves between "
            "Indian and British perspectives, with three structural parts: "
            "Mosque, Caves, and Temple."
        ),
        theme_examples=(
            "'empire', 'friendship', 'race', 'religion', 'mystery', 'justice', "
            "'muddle', 'echo', 'landscape', 'hospitality', 'trial', 'hinduism', "
            "'islam', 'christianity', 'bridge', 'separation'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Dr Aziz' not 'Aziz', 'Mrs Moore' not "
            "'the old lady', 'Adela Quested' not 'Adela', 'Cyril Fielding' not "
            "'Fielding'). Include characters referenced indirectly."
        ),
    ),
}


def get_novel_arcs(novel_key: str | None = None) -> list[tuple[str, str, int, str, str, int]]:
    """Return (name, character, demand, require_field, require_value, prefer_min_interest) tuples.

    These replace DEFAULT_ARCS when running on a non-BH novel.
    Returns None for Bleak House (use DEFAULT_ARCS).
    """
    if novel_key is None:
        import os
        novel_key = os.environ.get("BLEAKHOUSE_NOVEL")
    if not novel_key:
        return []

    arcs: dict[str, list[tuple[str, str, int, str, str, int]]] = {
        "our_mutual_friend": [
            ("Bella's transformation", "Bella Wilfer", 6,
             "prov_character_development", "not_none", 3),
            ("Harmon's disguise", "John Harmon", 5,
             "prov_plot_advancement", "not_none", 3),
            ("The Dust Heaps", "Nicodemus Boffin", 4,
             "prov_social_critique", "not_none", 2),
        ],
        "mill_on_the_floss": [
            ("Maggie's intellectual hunger", "Maggie Tulliver", 6,
             "prov_character_development", "not_none", 3),
            ("Tom and Maggie's rift", "Tom Tulliver", 5,
             "prov_character_development", "not_none", 3),
            ("The Tulliver ruin", "Mr Tulliver", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "north_and_south": [
            ("Margaret's transformation", "Margaret Hale", 6,
             "prov_character_development", "not_none", 3),
            ("Thornton and the strike", "John Thornton", 5,
             "prov_social_critique", "not_none", 3),
            ("Higgins and class solidarity", "Nicholas Higgins", 4,
             "prov_social_critique", "not_none", 2),
        ],
        "passage_to_india": [
            ("Aziz's humiliation and trial", "Dr Aziz", 6,
             "prov_character_development", "not_none", 3),
            ("The Marabar Caves", "Adela Quested", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Fielding's disillusion", "Cyril Fielding", 4,
             "prov_thematic_depth", "not_none", 2),
        ],
    }
    return arcs.get(novel_key, [])


_BLEAK_HOUSE_DEFAULT = NovelPromptConfig(
    title="Bleak House",
    author="Charles Dickens",
    year="1853",
    narration_note="",
    theme_examples="",
    character_note="",
)


def get_active_novel(novel_key: str | None = None) -> NovelPromptConfig:
    """Return the config for the specified novel.

    Args:
        novel_key: Explicit novel key (e.g. 'mill_on_the_floss').
                   If None, falls back to BLEAKHOUSE_NOVEL env var with a warning.
                   If neither is set, raises ValueError.
    """
    import logging
    import os

    if novel_key is None:
        novel_key = os.environ.get("BLEAKHOUSE_NOVEL")
        if novel_key:
            logging.getLogger(__name__).warning(
                "Novel set via BLEAKHOUSE_NOVEL env var (%s). "
                "Prefer passing --novel explicitly.",
                novel_key,
            )

    if not novel_key:
        raise ValueError(
            "No novel specified. Pass --novel to the CLI command, or set "
            "BLEAKHOUSE_NOVEL env var. There is no default — this prevents "
            "silent generation of the wrong novel's content."
        )

    if novel_key == "bleak_house":
        return _BLEAK_HOUSE_DEFAULT
    if novel_key in NOVEL_CONFIGS:
        return NOVEL_CONFIGS[novel_key]

    available = ["bleak_house"] + sorted(NOVEL_CONFIGS.keys())
    raise ValueError(
        f"Unknown novel key '{novel_key}'. Available: {', '.join(available)}"
    )


def build_enrichment_prompt(novel_key: str) -> str:
    """Build a novel-specific enrichment system prompt."""
    cfg = NOVEL_CONFIGS[novel_key]
    return f"""\
You are a literary analyst preparing paragraph-level annotations of {cfg.author}'s \
*{cfg.title}* for a podcast production team. Your job is to enrich every paragraph so \
producers can quickly find the most interesting material.

## Context

{cfg.narration_note}

## Your Task

For each paragraph marked with [P{{n}}], produce a `ParagraphEnrichment` object with:
- The `paragraph_index` matching the [P{{n}}] marker
- A `FieldReportEnrichment` covering interest, characters, narrator, plot function, \
  emotional register, themes, quotability, accessibility, summary, and provision \
  dimensions

## Guidelines

- **Interest scores**: Be discriminating. Most paragraphs are routine \
  connective prose (score 0-1). Reserve 4-5 for genuinely remarkable passages.
- **Characters**: {cfg.character_note}
- **Narrator detection**: Identify the narrative voice from textual cues \
  (person, tense, register).
- **Themes**: Use short lowercase tags. Common themes in *{cfg.title}*: {cfg.theme_examples}.
- **Quotability**: "strong" means a line a podcast host would read aloud for effect.
- **Provision dimensions**: Score honestly. Most paragraphs provide "none" or "weak" \
  on most dimensions. A paragraph that scores "strong" on multiple dimensions is \
  genuinely exceptional.
- **best_quote**: Extract verbatim from the text. Use null if nothing is quotable.
- Cover EVERY paragraph. Do not skip any [P{{n}}] markers.
"""
