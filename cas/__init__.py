"""Content-addressed store for BleakHouse.

Replaces DVC for blob storage. Bytes are addressed by md5; the same
md5 finds bytes both locally (under <BLEAKHOUSE_CAS_ROOT>/files/md5/...)
and on R2 (under /files/md5/...).

Public API lives in cas.store and cas.paths; this __init__ stays empty
during the build-out so the package imports cleanly at every commit.
Task 5 adds the re-exports once both modules exist.
"""
