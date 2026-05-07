"""Content-addressed store for BleakHouse.

Replaces DVC for blob storage. Bytes are addressed by md5; the same
md5 finds bytes both locally (under <BLEAKHOUSE_CAS_ROOT>/files/md5/...)
and on R2 (under /files/md5/...).

Public API re-exported here; full surface in cas.store and cas.paths.
"""
from cas import paths
from cas.store import (
    has_local,
    has_remote,
    local_path,
    pull,
    push,
    put,
    url,
)

__all__ = [
    "has_local",
    "has_remote",
    "local_path",
    "paths",
    "pull",
    "push",
    "put",
    "url",
]
