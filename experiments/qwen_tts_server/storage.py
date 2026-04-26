"""Per-job filesystem layout under <jobs_dir>/<job_id>/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobStorage:
    jobs_dir: Path
    job_id: str

    @property
    def root(self) -> Path:
        return self.jobs_dir / self.job_id

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    @property
    def refs(self) -> Path:
        return self.root / "refs"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def log(self) -> Path:
        return self.root / "log.txt"

    def create(self) -> None:
        for d in (self.inputs, self.refs, self.out):
            d.mkdir(parents=True, exist_ok=True)

    def save_input(self, name: str, data: bytes) -> Path:
        # `name` is a fixed kind ("manifest.json" / "phase3_episode.json" /
        # "ref_source.mp3") chosen by the server, never user-controlled.
        path = self.inputs / name
        path.write_bytes(data)
        return path

    def result_path(self, name: str) -> Path:
        # `name` is taken from the request URL — must be confined to self.out.
        candidate = (self.out / name).resolve()
        out_resolved = self.out.resolve()
        try:
            candidate.relative_to(out_resolved)
        except ValueError as exc:
            raise ValueError(f"path escapes out dir: {name!r}") from exc
        return candidate
