"""Pipeline run configuration — captures every parameter that affects output.

A RunConfig is a complete, serializable snapshot of the decisions a producer
makes: how many passages to select, how aggressively to penalize redundancy,
which segments to build, and which model to use for script generation.

Variants are built by overriding fields on a baseline config.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    DEFAULT_PERSONAS,
    DEFAULT_SEGMENT_TEMPLATES,
    ExpertPersona,
    SegmentTemplate,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    ArcDemand,
    ExpertProfile,
    ProducerConfig,
)

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"


@dataclass
class RunConfig:
    """Complete configuration for a pipeline run."""

    name: str

    # Phase 1: passage selection
    producer: ProducerConfig = field(default_factory=ProducerConfig)
    experts: list[ExpertProfile] = field(default_factory=lambda: list(DEFAULT_EXPERTS))
    arcs: list[ArcDemand] = field(default_factory=lambda: list(DEFAULT_ARCS))

    # Phase 2: segment assignment
    segment_templates: list[SegmentTemplate] = field(
        default_factory=lambda: list(DEFAULT_SEGMENT_TEMPLATES)
    )
    segment_null_cost: int = 50
    segment_dimension_mismatch_cost: int = 5
    segment_arc_mismatch_cost: int = 3
    segment_expert_mismatch_cost: int = 2

    # Prompt version (1 = original, 2 = supply-aware + passage-grounded quoting)
    prompt_version: int = 2

    # Phase 3: script generation
    model: str = "claude-sonnet-4-6"
    personas: list[ExpertPersona] = field(
        default_factory=lambda: list(DEFAULT_PERSONAS)
    )

    # Phase 4: audio rendering
    tts_model: str = "flash"

    def run_dir(self) -> Path:
        return RUNS_DIR / self.name

    def save(self) -> None:
        """Save config to the run directory."""
        d = self.run_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / "config.json"
        data = {
            "name": self.name,
            "producer": asdict(self.producer),
            "experts": [asdict(e) for e in self.experts],
            "arcs": [asdict(a) for a in self.arcs],
            "segment_templates": [t.model_dump() for t in self.segment_templates],
            "segment_null_cost": self.segment_null_cost,
            "segment_dimension_mismatch_cost": self.segment_dimension_mismatch_cost,
            "segment_arc_mismatch_cost": self.segment_arc_mismatch_cost,
            "segment_expert_mismatch_cost": self.segment_expert_mismatch_cost,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "personas": [p.model_dump() for p in self.personas],
            "tts_model": self.tts_model,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, name: str) -> RunConfig:
        """Load a saved config by run name."""
        path = RUNS_DIR / name / "config.json"
        with open(path) as f:
            data = json.load(f)
        return cls(
            name=data["name"],
            producer=ProducerConfig(**data["producer"]),
            experts=[ExpertProfile(**e) for e in data["experts"]],
            arcs=[ArcDemand(**a) for a in data["arcs"]],
            segment_templates=[
                SegmentTemplate.model_validate(t) for t in data["segment_templates"]
            ],
            segment_null_cost=data.get("segment_null_cost", 50),
            segment_dimension_mismatch_cost=data.get(
                "segment_dimension_mismatch_cost", 5
            ),
            segment_arc_mismatch_cost=data.get("segment_arc_mismatch_cost", 3),
            segment_expert_mismatch_cost=data.get("segment_expert_mismatch_cost", 2),
            prompt_version=data.get("prompt_version", 1),
            model=data.get("model", "claude-sonnet-4-6"),
            personas=[
                ExpertPersona.model_validate(p)
                for p in data.get("personas", [])
            ]
            or list(DEFAULT_PERSONAS),
            tts_model=data.get("tts_model", "flash"),
        )

    def describe_diff(self, other: RunConfig) -> str:
        """One-line summary of what changed between two configs."""
        diffs: list[str] = []
        if self.producer != other.producer:
            mine = asdict(self.producer)
            theirs = asdict(other.producer)
            for k in mine:
                if mine[k] != theirs[k]:
                    diffs.append(f"{k}: {mine[k]} → {theirs[k]}")
        if len(self.arcs) != len(other.arcs):
            diffs.append(f"arcs: {len(self.arcs)} → {len(other.arcs)}")
        else:
            for a, b in zip(self.arcs, other.arcs):
                if asdict(a) != asdict(b):
                    diffs.append(f"arc '{a.name}' changed")
        if len(self.segment_templates) != len(other.segment_templates):
            diffs.append(
                f"segments: {len(self.segment_templates)} → {len(other.segment_templates)}"
            )
        if self.model != other.model:
            diffs.append(f"model: {self.model} → {other.model}")
        return "; ".join(diffs) if diffs else "identical"
