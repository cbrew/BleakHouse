"""Server config: paths, port, token loader.

Defaults match the systemd-managed install layout. Override via env for tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    state_dir: Path
    jobs_dir: Path
    db_path: Path
    token_path: Path
    bind_host: str
    bind_port: int
    code_rev_path: Path | None

    @classmethod
    def from_env(cls) -> "Config":
        state = Path(os.environ.get("QWEN_TTS_STATE_DIR", "/var/lib/qwen-tts-server"))
        return cls(
            state_dir=state,
            jobs_dir=state / "jobs",
            db_path=state / "jobs.db",
            token_path=Path(os.environ.get("QWEN_TTS_TOKEN_PATH", "/etc/qwen-tts-server/token")),
            bind_host=os.environ.get("QWEN_TTS_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("QWEN_TTS_PORT", "8765")),
            code_rev_path=Path(os.environ["QWEN_TTS_CODE_REV"]) if "QWEN_TTS_CODE_REV" in os.environ else None,
        )

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def load_token(self) -> str:
        return self.token_path.read_text().strip()

    def code_rev(self) -> str:
        if self.code_rev_path and self.code_rev_path.exists():
            return self.code_rev_path.read_text().strip()
        return "unknown"
