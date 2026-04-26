"""Idempotency hash over input files + renderer code rev."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path


def job_hash(files: Sequence[Path], *, code_rev: str, chunk: int = 1 << 20) -> str:
    """sha256 over (each file's bytes, in given order) + code_rev sentinel.

    Order matters: ``[a, b]`` and ``[b, a]`` produce different hashes so callers
    must canonicalise the file list before passing it in.
    """
    h = hashlib.sha256()
    for path in files:
        with path.open("rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
        h.update(b"\x00FILEBOUNDARY\x00")
    h.update(b"\x00CODEREV\x00")
    h.update(code_rev.encode())
    return h.hexdigest()
