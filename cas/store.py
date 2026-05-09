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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3

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


def _bucket() -> str:
    return os.environ.get("BLEAKHOUSE_R2_BUCKET", "not-in-our-time")


def _r2_client():  # type: ignore[no-untyped-def]
    """Construct a fresh boto3 S3 client.

    Required env vars: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY.
    Optional env var: R2_ENDPOINT_URL (omit for moto/test use).
    Raises KeyError on missing required var.
    """
    import boto3
    kwargs: dict[str, object] = {
        "aws_access_key_id": os.environ["R2_ACCESS_KEY_ID"],
        "aws_secret_access_key": os.environ["R2_SECRET_ACCESS_KEY"],
        "region_name": "auto",
    }
    endpoint = os.environ.get("R2_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def _r2_key(md5: str) -> str:
    return f"files/md5/{md5[:2]}/{md5[2:]}"


def has_remote(md5: str) -> bool:
    """True if R2 has the blob (HEAD check)."""
    from botocore.exceptions import ClientError
    try:
        _r2_client().head_object(Bucket=_bucket(), Key=_r2_key(md5))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def push(md5: str) -> None:
    """Upload local blob to R2. Idempotent (HEAD-then-PUT).

    Raises FileNotFoundError if blob missing locally.
    """
    src = local_path(md5)
    if src is None:
        raise FileNotFoundError(f"md5 {md5} not in local CAS")
    if has_remote(md5):
        return
    with src.open("rb") as f:
        _r2_client().put_object(Bucket=_bucket(), Key=_r2_key(md5), Body=f)


def pull(md5: str) -> Path:
    """Download blob from R2 into local CAS; return local path.

    Raises FileNotFoundError if blob missing in R2.
    """
    dest = _cas_path_for(md5)
    if dest.is_file():
        return dest
    from botocore.exceptions import ClientError
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=dest.parent, prefix=".pull-", suffix=".tmp", delete=False
    ) as tmp_f:
        tmp = Path(tmp_f.name)
    try:
        _r2_client().download_file(_bucket(), _r2_key(md5), str(tmp))
        tmp.rename(dest)
    except ClientError as exc:
        tmp.unlink(missing_ok=True)
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(f"md5 {md5} not in R2") from exc
        raise
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest
