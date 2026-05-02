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
    # --- New novels for generalization study ---
    "hard_times": NovelPromptConfig(
        title="Hard Times",
        author="Charles Dickens",
        year="1854",
        narration_note=(
            "*Hard Times* uses third-person omniscient narration. Dickens's "
            "shortest novel, structured in three books (Sowing, Reaping, "
            "Garnering). The narration is more polemical than in his other novels, "
            "directly attacking utilitarianism and industrial exploitation."
        ),
        theme_examples=(
            "'utilitarianism', 'education', 'imagination', 'industry', 'class', "
            "'marriage', 'circus', 'fact', 'fancy', 'labour', 'strikes', 'poverty', "
            "'hypocrisy', 'divorce', 'statistics'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Thomas Gradgrind' not 'Gradgrind', "
            "'Josiah Bounderby' not 'Bounderby', 'Louisa Gradgrind' not 'Louisa', "
            "'Stephen Blackpool' not 'Stephen', 'Sissy Jupe' not 'Sissy'). "
            "Include characters referenced indirectly."
        ),
    ),
    "middlemarch": NovelPromptConfig(
        title="Middlemarch",
        author="George Eliot",
        year="1871",
        narration_note=(
            "*Middlemarch* uses third-person omniscient narration with Eliot's "
            "characteristic philosophical commentary. The novel weaves four major "
            "plot strands set in a provincial English town during 1829-1832, "
            "with frequent authorial generalisation about human nature."
        ),
        theme_examples=(
            "'vocation', 'marriage', 'reform', 'science', 'religion', 'money', "
            "'ambition', 'idealism', 'provincial', 'politics', 'duty', 'sympathy', "
            "'egoism', 'knowledge', 'women', 'inheritance'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Dorothea Brooke' not 'Dorothea', "
            "'Tertius Lydgate' not 'Lydgate', 'Edward Casaubon' not 'Casaubon', "
            "'Rosamond Vincy' not 'Rosamond', 'Fred Vincy' not 'Fred', "
            "'Will Ladislaw' not 'Will', 'Nicholas Bulstrode' not 'Bulstrode'). "
            "Include characters referenced indirectly."
        ),
    ),
    "daniel_deronda": NovelPromptConfig(
        title="Daniel Deronda",
        author="George Eliot",
        year="1876",
        narration_note=(
            "*Daniel Deronda* uses third-person omniscient narration. The novel "
            "interweaves two plot strands: Gwendolen Harleth's marriage and moral "
            "development, and Daniel Deronda's discovery of his Jewish heritage. "
            "Eliot's narration is philosophically dense, especially in the "
            "Deronda chapters."
        ),
        theme_examples=(
            "'identity', 'judaism', 'nationalism', 'marriage', 'gambling', "
            "'music', 'vocation', 'sympathy', 'egoism', 'duty', 'inheritance', "
            "'class', 'empire', 'art', 'zionism', 'rescue'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Gwendolen Harleth' not 'Gwendolen', "
            "'Daniel Deronda' not 'Deronda', 'Henleigh Grandcourt' not "
            "'Grandcourt', 'Mirah Lapidoth' not 'Mirah', 'Mordecai' not 'Ezra'). "
            "Include characters referenced indirectly."
        ),
    ),
    "david_copperfield": NovelPromptConfig(
        title="David Copperfield",
        author="Charles Dickens",
        year="1850",
        narration_note=(
            "*David Copperfield* uses first-person retrospective narration "
            "throughout. The adult David looks back on his life from childhood, "
            "giving the novel a distinctive blend of naive and mature perspectives. "
            "Dickens considered it his 'favourite child' among his novels."
        ),
        theme_examples=(
            "'memory', 'childhood', 'education', 'class', 'marriage', 'ambition', "
            "'discipline', 'undisciplined heart', 'writing', 'poverty', 'cruelty', "
            "'friendship', 'betrayal', 'emigration', 'perseverance'"
        ),
        character_note=(
            "Use canonical names (e.g. 'David Copperfield' not 'David', "
            "'Edward Murdstone' not 'Murdstone', 'Betsey Trotwood' not 'Aunt', "
            "'James Steerforth' not 'Steerforth', 'Uriah Heep' not 'Heep', "
            "'Agnes Wickfield' not 'Agnes', 'Mr Micawber' not 'Micawber'). "
            "Include characters referenced indirectly."
        ),
    ),
    "cranford": NovelPromptConfig(
        title="Cranford",
        author="Elizabeth Gaskell",
        year="1853",
        narration_note=(
            "*Cranford* uses first-person narration by Mary Smith, a younger "
            "visitor who observes the lives of the elderly gentlewomen of a small "
            "English town. The novel is episodic, originally published as "
            "magazine sketches. The tone is comic and affectionate."
        ),
        theme_examples=(
            "'gentility', 'poverty', 'community', 'manners', 'death', 'age', "
            "'women', 'economy', 'gossip', 'propriety', 'kindness', 'change', "
            "'snobbery', 'friendship', 'elegance'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Miss Matty' or 'Miss Matilda Jenkyns' "
            "not 'Matty', 'Miss Deborah Jenkyns' not 'Deborah', "
            "'Captain Brown' not 'the Captain', 'Mary Smith' for the narrator). "
            "Include characters referenced indirectly."
        ),
    ),
    "no_name": NovelPromptConfig(
        title="No Name",
        author="Wilkie Collins",
        year="1862",
        narration_note=(
            "*No Name* uses third-person narration alternating with epistolary "
            "sections ('Between the Scenes'). Collins structures the novel as "
            "a series of dramatic scenes separated by letters and documents. "
            "The narration is plot-driven and theatrical."
        ),
        theme_examples=(
            "'illegitimacy', 'identity', 'inheritance', 'disguise', 'deception', "
            "'law', 'marriage', 'revenge', 'respectability', 'sisters', "
            "'performance', 'will', 'disinheritance', 'determination'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Magdalen Vanstone' not 'Magdalen', "
            "'Norah Vanstone' not 'Norah', 'Captain Wragge' not 'Wragge', "
            "'Noel Vanstone' not 'Noel', 'Mrs Lecount' not 'Lecount'). "
            "Include characters referenced indirectly."
        ),
    ),
    "new_grub_street": NovelPromptConfig(
        title="New Grub Street",
        author="George Gissing",
        year="1891",
        narration_note=(
            "*New Grub Street* uses third-person omniscient narration. The novel "
            "follows the contrasting fortunes of writers in the literary "
            "marketplace of 1880s London. Gissing's narration is precise and "
            "unsentimental, with a naturalist's eye for economic determinism."
        ),
        theme_examples=(
            "'writing', 'money', 'ambition', 'poverty', 'marriage', 'journalism', "
            "'commercialism', 'art', 'class', 'failure', 'compromise', "
            "'respectability', 'literary market', 'integrity'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Edwin Reardon' not 'Reardon', "
            "'Jasper Milvain' not 'Milvain', 'Alfred Yule' not 'Yule', "
            "'Marian Yule' not 'Marian', 'Amy Reardon' not 'Amy', "
            "'Harold Biffen' not 'Biffen'). Include characters referenced indirectly."
        ),
    ),
    "room_with_a_view": NovelPromptConfig(
        title="A Room with a View",
        author="E. M. Forster",
        year="1908",
        narration_note=(
            "*A Room with a View* uses third-person narration with a wry, "
            "ironic register, free-indirect access to Lucy Honeychurch's "
            "consciousness, and Forster's signature commentary voice. The "
            "novel divides between an Italian first part (Pension Bertolini "
            "in Florence) and an English second part (the Honeychurch home "
            "in Surrey, then briefly Rome). The tone is comic but precise; "
            "the satire targets Edwardian social codes."
        ),
        theme_examples=(
            "'class', 'propriety', 'aestheticism', 'tourism', 'Italy', "
            "'England', 'youth', 'self-deception', 'sincerity', 'art', "
            "'religion', 'sex', 'marriage', 'liberation', 'view'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Lucy Honeychurch' not 'Lucy', "
            "'George Emerson' not 'George', 'Mr Emerson' for the father, "
            "'Charlotte Bartlett' not 'Charlotte' or 'Cousin', "
            "'Cecil Vyse' not 'Cecil', 'Mr Beebe' not 'Beebe', "
            "'Miss Lavish' not 'Eleanor', 'Mr Eager' not 'Eager', "
            "'Mrs Honeychurch' not 'Marian', 'Freddy Honeychurch' not 'Freddy'). "
            "Include characters referenced indirectly."
        ),
    ),
    "odd_women": NovelPromptConfig(
        title="The Odd Women",
        author="George Gissing",
        year="1893",
        narration_note=(
            "*The Odd Women* uses third-person omniscient narration. The novel "
            "follows several unmarried women navigating limited options in "
            "1890s London. Gissing is sympathetic but unsentimental, examining "
            "gender politics through contrasting strategies of survival."
        ),
        theme_examples=(
            "'women', 'marriage', 'independence', 'work', 'poverty', 'feminism', "
            "'education', 'class', 'typewriting', 'celibacy', 'temptation', "
            "'pride', 'compromise', 'equality'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Rhoda Nunn' not 'Rhoda', "
            "'Monica Madden' not 'Monica', 'Edmund Widdowson' not 'Widdowson', "
            "'Mary Barfoot' not 'Miss Barfoot', 'Everard Barfoot' not 'Barfoot', "
            "'Virginia Madden' not 'Virginia'). Include characters referenced "
            "indirectly."
        ),
    ),
    "miss_marjoribanks": NovelPromptConfig(
        title="Miss Marjoribanks",
        author="Mrs Oliphant",
        year="1866",
        narration_note=(
            "*Miss Marjoribanks* uses third-person omniscient narration with "
            "Oliphant's characteristic ironic wit. The novel follows Lucilla "
            "Marjoribanks as she 'reforms' the social life of Carlingford. "
            "The tone blends domestic comedy with sharp social observation."
        ),
        theme_examples=(
            "'society', 'ambition', 'marriage', 'influence', 'domesticity', "
            "'propriety', 'power', 'election', 'duty', 'reform', 'gossip', "
            "'entertainment', 'provincial', 'management'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Lucilla Marjoribanks' not 'Lucilla', "
            "'Dr Marjoribanks' not 'the Doctor', 'Tom Marjoribanks' not 'Tom', "
            "'Mrs Woodburn' not 'the Woodburns'). Include characters referenced "
            "indirectly."
        ),
    ),
    "hester": NovelPromptConfig(
        title="Hester",
        author="Mrs Oliphant",
        year="1883",
        narration_note=(
            "*Hester* uses third-person omniscient narration. The novel centres "
            "on the Vernon family and their bank in Redborough. Oliphant "
            "explores women's relationship to money, power, and independence "
            "through the conflict between Catherine Vernon and Hester."
        ),
        theme_examples=(
            "'banking', 'money', 'power', 'women', 'independence', 'reputation', "
            "'family', 'gratitude', 'resentment', 'speculation', 'crisis', "
            "'marriage', 'intelligence', 'dependence'"
        ),
        character_note=(
            "Use canonical names (e.g. 'Hester Vernon' not 'Hester', "
            "'Catherine Vernon' not 'Catherine', 'Edward Vernon' not 'Edward', "
            "'Harry Vernon' not 'Harry', 'Mrs John Vernon' not 'Hester's mother'). "
            "Include characters referenced indirectly."
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
        # --- New novels for generalization study ---
        "hard_times": [
            ("Louisa's deadened inner life", "Louisa Gradgrind", 6,
             "prov_character_development", "not_none", 3),
            ("Stephen's injustice", "Stephen Blackpool", 5,
             "prov_social_critique", "not_none", 3),
            ("Gradgrind's reckoning", "Thomas Gradgrind", 4,
             "prov_thematic_depth", "not_none", 2),
        ],
        "middlemarch": [
            ("Dorothea's disillusion and growth", "Dorothea Brooke", 6,
             "prov_character_development", "not_none", 3),
            ("Lydgate's professional ruin", "Tertius Lydgate", 5,
             "prov_character_development", "not_none", 3),
            ("Bulstrode's exposure", "Nicholas Bulstrode", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "daniel_deronda": [
            ("Gwendolen's moral awakening", "Gwendolen Harleth", 6,
             "prov_character_development", "not_none", 3),
            ("Deronda's discovery of identity", "Daniel Deronda", 5,
             "prov_thematic_depth", "not_none", 3),
            ("Grandcourt's tyranny", "Henleigh Grandcourt", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "david_copperfield": [
            ("David's undisciplined heart", "David Copperfield", 6,
             "prov_character_development", "not_none", 3),
            ("Steerforth's betrayal", "James Steerforth", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Uriah Heep's scheming", "Uriah Heep", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "cranford": [
            ("Miss Matty's genteel poverty", "Miss Matty", 6,
             "prov_character_development", "not_none", 3),
            ("Captain Brown's death", "Captain Brown", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Peter's return", "Peter Jenkyns", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "no_name": [
            ("Magdalen's campaign of deception", "Magdalen Vanstone", 6,
             "prov_character_development", "not_none", 3),
            ("The inheritance plot", "Noel Vanstone", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Captain Wragge's schemes", "Captain Wragge", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "new_grub_street": [
            ("Reardon's decline", "Edwin Reardon", 6,
             "prov_character_development", "not_none", 3),
            ("Milvain's rise", "Jasper Milvain", 5,
             "prov_social_critique", "not_none", 3),
            ("Marian's trapped position", "Marian Yule", 4,
             "prov_character_development", "not_none", 2),
        ],
        "odd_women": [
            ("Rhoda's principles tested", "Rhoda Nunn", 6,
             "prov_character_development", "not_none", 3),
            ("Monica's desperate marriage", "Monica Madden", 5,
             "prov_character_development", "not_none", 3),
            ("Widdowson's jealousy", "Edmund Widdowson", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "miss_marjoribanks": [
            ("Lucilla's social campaign", "Lucilla Marjoribanks", 6,
             "prov_character_development", "not_none", 3),
            ("The Cavendish scandal", "Mr Cavendish", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Tom's return", "Tom Marjoribanks", 4,
             "prov_plot_advancement", "not_none", 2),
        ],
        "hester": [
            ("Hester's frustrated ambition", "Hester Vernon", 6,
             "prov_character_development", "not_none", 3),
            ("Edward's speculation and flight", "Edward Vernon", 5,
             "prov_plot_advancement", "not_none", 3),
            ("Catherine's power and loneliness", "Catherine Vernon", 4,
             "prov_thematic_depth", "not_none", 2),
        ],
        "room_with_a_view": [
            ("Lucy's awakening from propriety", "Lucy Honeychurch", 6,
             "prov_character_development", "not_none", 3),
            ("George Emerson's philosophy of being yourself", "George Emerson", 5,
             "prov_thematic_depth", "not_none", 3),
            ("Charlotte Bartlett and Edwardian propriety", "Charlotte Bartlett", 4,
             "prov_social_critique", "not_none", 2),
            ("The Pension Bertolini as theatre of class", "Mr Eager", 4,
             "prov_social_critique", "not_none", 2),
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
