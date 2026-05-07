"""Content-addressed store: bytes by md5.

Local layer: hash + copy into <BLEAKHOUSE_CAS_ROOT>/files/md5/<prefix>/<rest>.
R2 layer: upload/download via boto3 (added in Task 3).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

# Repo root is two levels up from this file (cas/store.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _cas_root() -> Path:
    """Local CAS root. Default <repo>/data/cas; overridable via env var."""
    override = os.environ.get("BLEAKHOUSE_CAS_ROOT")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "cas"


def _cas_path_for(md5: str) -> Path:
    """Compute the on-disk path for an md5 (regardless of existence)."""
    return _cas_root() / "files" / "md5" / md5[:2] / md5[2:]


def _r2_public_url() -> str:
    return os.environ.get(
        "BLEAKHOUSE_R2_PUBLIC_URL",
        "https://pub-0ac622dd336f40438799d8dbd211234a.r2.dev",
    )


def url(md5: str) -> str:
    """Public R2 URL for the blob with this md5."""
    return f"{_r2_public_url()}/files/md5/{md5[:2]}/{md5[2:]}"


def put(path: Path) -> str:
    """Hash `path`, copy bytes into the CAS, return md5.

    Idempotent: if md5 already in CAS, no copy. Reads-and-copies
    (does not move/link); caller is responsible for the source file.
    """
    md5 = _md5_of_file(path)
    dest = _cas_path_for(md5)
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile in dest.parent guarantees a unique name even
        # under concurrent puts of the same md5; same-FS rename is atomic.
        with tempfile.NamedTemporaryFile(
            dir=dest.parent, prefix=".put-", suffix=".tmp", delete=False
        ) as tmp_f:
            tmp = Path(tmp_f.name)
        try:
            shutil.copyfile(path, tmp)
            tmp.rename(dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    return md5


def local_path(md5: str) -> Path | None:
    """On-disk path if blob is in local CAS, else None."""
    p = _cas_path_for(md5)
    return p if p.is_file() else None


def has_local(md5: str) -> bool:
    return local_path(md5) is not None


def _md5_of_file(path: Path) -> str:
    # usedforsecurity=False is a no-op outside FIPS but lets the call
    # work in FIPS-mode environments where md5 is otherwise rejected.
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
