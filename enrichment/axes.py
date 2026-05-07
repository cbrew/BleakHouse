"""Canonical axes for run directories.

A run directory represents one generated podcast episode. It has five axes:

    - novel:     source text (bh, omf, mid, dd, ...)
    - pipeline:  how passages are chosen (trn, emb, nop, rag)
    - panel:     expert panel (literary, interdisciplinary, alternatives)
    - hostprep:  whether Phase 2.5 host briefs were generated and used
    - generator: which LLM produced the Phase 3 script

These axes are the source of truth. Run directory names are derived from
them deterministically via `run_dir_name()`; `parse_run_dir_name()` is the
inverse. `RunAxes` carries the tuple; `config.json["axes"]` is the on-disk
form via `RunAxes.to_dict / from_dict`.

Back-compat: when `generator == DEFAULT_GENERATOR` (anthropic_sonnet_4_6),
the generator suffix is omitted from the directory name so existing runs
keep their shape. Everything else is always present.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Novel:
    key: str
    id: str
    title: str
    author: str
    year: int


NOVELS: tuple[Novel, ...] = (
    Novel("bh", "bleak_house", "Bleak House", "Dickens", 1853),
    Novel("omf", "our_mutual_friend", "Our Mutual Friend", "Dickens", 1865),
    Novel("dc", "david_copperfield", "David Copperfield", "Dickens", 1850),
    Novel("ht", "hard_times", "Hard Times", "Dickens", 1854),
    Novel("motf", "mill_on_the_floss", "Mill on the Floss", "Eliot", 1860),
    Novel("mid", "middlemarch", "Middlemarch", "Eliot", 1871),
    Novel("dd", "daniel_deronda", "Daniel Deronda", "Eliot", 1876),
    Novel("nas", "north_and_south", "North and South", "Gaskell", 1855),
    Novel("cran", "cranford", "Cranford", "Gaskell", 1853),
    Novel("pti", "passage_to_india", "Passage to India", "Forster", 1924),
    Novel("noname", "no_name", "No Name", "Collins", 1862),
    Novel("ngs", "new_grub_street", "New Grub Street", "Gissing", 1891),
    Novel("oddw", "odd_women", "The Odd Women", "Gissing", 1893),
    Novel("mmar", "miss_marjoribanks", "Miss Marjoribanks", "Oliphant", 1866),
    Novel("hest", "hester", "Hester", "Oliphant", 1883),
    Novel("rwv", "room_with_a_view", "A Room with a View", "Forster", 1908),
    Novel("ot", "oliver_twist", "Oliver Twist", "Dickens", 1838),
    Novel("mdal", "mrs_dalloway", "Mrs. Dalloway", "Woolf", 1925),
)

NOVEL_KEYS: frozenset[str] = frozenset(n.key for n in NOVELS)
NOVEL_IDS: frozenset[str] = frozenset(n.id for n in NOVELS)
NOVEL_BY_KEY: dict[str, Novel] = {n.key: n for n in NOVELS}
NOVEL_BY_ID: dict[str, Novel] = {n.id: n for n in NOVELS}


PIPELINES: frozenset[str] = frozenset({"trn", "emb", "nop", "rag"})


@dataclass(frozen=True)
class Panel:
    id: str
    experts: tuple[str, ...]
    display: str


PANELS_TUPLE: tuple[Panel, ...] = (
    Panel(
        "literary",
        ("Eleanor Hartley", "James Blackstone", "Caroline Woodcourt"),
        "Literary (Hartley / Blackstone / Woodcourt)",
    ),
    Panel(
        "interdisciplinary",
        ("Sarah Chen", "Rebecca Martinez", "Elena Volkov"),
        "Interdisciplinary (Chen / Martinez / Volkov)",
    ),
    Panel(
        "alternatives",
        ("Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan"),
        "Alternatives (Leigh / Rosen / Trevelyan)",
    ),
)

PANELS: frozenset[str] = frozenset(p.id for p in PANELS_TUPLE)
PANEL_BY_ID: dict[str, Panel] = {p.id: p for p in PANELS_TUPLE}


def panel_for_experts(expert_names: Iterable[str]) -> str | None:
    """Return the panel id whose experts exactly match the given names."""
    s = frozenset(expert_names)
    for p in PANELS_TUPLE:
        if frozenset(p.experts) == s:
            return p.id
    return None


HOSTPREP_VALUES: tuple[bool, ...] = (False, True)


@dataclass(frozen=True)
class Generator:
    id: str
    api_model: str
    provider: str
    display: str


def _load_generators_from_params() -> tuple[Generator, ...]:
    """Read generator definitions from DVC-tracked params.yaml so the set
    of known generators / their api_model bindings can change without
    editing Python code — and so DVC sees the change."""
    # Lazy import to avoid a hard coupling when axes.py is consumed by
    # environments that don't have the repo root available (e.g. tests
    # that import enrichment.axes in isolation).
    from enrichment import params as _params

    raw = _params.get("generators", default=[]) or []
    generators: list[Generator] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"params.yaml generators: expected dict, got {entry!r}")
        generators.append(Generator(
            id=str(entry["id"]),
            api_model=str(entry["api_model"]),
            provider=str(entry["provider"]),
            display=str(entry["display"]),
        ))
    return tuple(generators)


GENERATORS_TUPLE: tuple[Generator, ...] = _load_generators_from_params()

GENERATORS: frozenset[str] = frozenset(g.id for g in GENERATORS_TUPLE)
GENERATOR_BY_ID: dict[str, Generator] = {g.id: g for g in GENERATORS_TUPLE}


def _default_generator_from_params() -> str:
    from enrichment import params as _params

    dg = _params.get("default_generator")
    return str(dg) if dg else "anthropic_sonnet_4_6"


DEFAULT_GENERATOR: str = _default_generator_from_params()


HOSTPREP_TOKEN: str = "hostprep"
LENGTH_TOKEN: str = "short"
LENGTHS: frozenset[str] = frozenset({"long", "short"})
DEFAULT_LENGTH: str = "long"


@dataclass(frozen=True)
class RunAxes:
    novel: str
    pipeline: str
    panel: str
    hostprep: bool
    generator: str = DEFAULT_GENERATOR
    length: str = DEFAULT_LENGTH

    def __post_init__(self) -> None:
        if self.novel not in NOVEL_KEYS:
            raise ValueError(f"unknown novel {self.novel!r}")
        if self.pipeline not in PIPELINES:
            raise ValueError(f"unknown pipeline {self.pipeline!r}")
        if self.panel not in PANELS:
            raise ValueError(f"unknown panel {self.panel!r}")
        if self.generator not in GENERATORS:
            raise ValueError(f"unknown generator {self.generator!r}")
        if self.length not in LENGTHS:
            raise ValueError(f"unknown length {self.length!r}")

    def to_dict(self) -> dict[str, object]:
        return {
            "novel": self.novel,
            "pipeline": self.pipeline,
            "panel": self.panel,
            "hostprep": self.hostprep,
            "generator": self.generator,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> RunAxes:
        return cls(
            novel=str(d["novel"]),
            pipeline=str(d["pipeline"]),
            panel=str(d["panel"]),
            hostprep=bool(d["hostprep"]),
            generator=str(d.get("generator", DEFAULT_GENERATOR)),
            length=str(d.get("length", DEFAULT_LENGTH)),
        )

    def dir_name(self) -> str:
        return run_dir_name(
            novel=self.novel,
            pipeline=self.pipeline,
            panel=self.panel,
            hostprep=self.hostprep,
            generator=self.generator,
            length=self.length,
        )


def run_dir_name(
    *,
    novel: str,
    pipeline: str,
    panel: str,
    hostprep: bool,
    generator: str = DEFAULT_GENERATOR,
    length: str = DEFAULT_LENGTH,
) -> str:
    """Build a canonical run directory name from explicit axis values.

    Rules:
      - `novel` in NOVEL_KEYS, `pipeline` in PIPELINES, `panel` in PANELS,
        `generator` in GENERATORS, `length` in LENGTHS; otherwise `ValueError`.
      - `hostprep=True` appends `_hostprep`.
      - `length == "short"` appends `_short` (after hostprep, before generator).
      - `generator != DEFAULT_GENERATOR` appends `_<generator>`; the default
        is omitted so pre-existing run dirs keep their shape.
    """
    if novel not in NOVEL_KEYS:
        raise ValueError(f"unknown novel {novel!r}")
    if pipeline not in PIPELINES:
        raise ValueError(f"unknown pipeline {pipeline!r}")
    if panel not in PANELS:
        raise ValueError(f"unknown panel {panel!r}")
    if generator not in GENERATORS:
        raise ValueError(f"unknown generator {generator!r}")
    if length not in LENGTHS:
        raise ValueError(f"unknown length {length!r}")

    parts = [novel, pipeline, panel]
    if hostprep:
        parts.append(HOSTPREP_TOKEN)
    if length != DEFAULT_LENGTH:
        parts.append(LENGTH_TOKEN)
    if generator != DEFAULT_GENERATOR:
        parts.append(generator)
    return "_".join(parts)


def parse_run_dir_name(name: str) -> RunAxes:
    """Invert `run_dir_name` — raise `ValueError` on any unknown token.

    The parser walks the first three tokens against novel/pipeline/panel
    vocabularies, optionally consumes the literal `hostprep`, optionally
    the literal `short`, and treats the remainder (which may itself
    contain underscores, e.g. `cerebras_qwen`) as the generator. Absent
    remainder → `DEFAULT_GENERATOR`.
    """
    parts = name.split("_")
    if len(parts) < 3:
        raise ValueError(f"run dir name {name!r} has too few tokens")

    novel, pipeline, panel = parts[0], parts[1], parts[2]
    remainder = parts[3:]

    if novel not in NOVEL_KEYS:
        raise ValueError(f"{name!r}: unknown novel {novel!r}")
    if pipeline not in PIPELINES:
        raise ValueError(f"{name!r}: unknown pipeline {pipeline!r}")
    if panel not in PANELS:
        raise ValueError(f"{name!r}: unknown panel {panel!r}")

    hostprep = False
    if remainder and remainder[0] == HOSTPREP_TOKEN:
        hostprep = True
        remainder = remainder[1:]

    length = DEFAULT_LENGTH
    if remainder and remainder[0] == LENGTH_TOKEN:
        length = "short"
        remainder = remainder[1:]

    if not remainder:
        generator = DEFAULT_GENERATOR
    else:
        generator = "_".join(remainder)
        if generator not in GENERATORS:
            raise ValueError(f"{name!r}: unknown generator {generator!r}")

    return RunAxes(
        novel=novel,
        pipeline=pipeline,
        panel=panel,
        hostprep=hostprep,
        generator=generator,
        length=length,
    )
