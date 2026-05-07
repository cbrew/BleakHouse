"""Tests for cas.store R2 API: push, pull, has_remote (moto-mocked)."""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from cas import store


def _make_bucket() -> None:
    """Create the test bucket inside the active moto mock.

    No endpoint_url: moto intercepts standard AWS S3 calls but does NOT
    intercept custom endpoint URLs, so we let boto3 use its default endpoint
    and let moto patch at the botocore level.
    """
    boto3.client(
        "s3",
        aws_access_key_id="test_access",
        aws_secret_access_key="test_secret",
        region_name="us-east-1",
    ).create_bucket(Bucket="test-bucket")


def test_has_remote_false_when_blob_absent(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        _make_bucket()
        assert store.has_remote("0" * 32) is False


def test_push_uploads_local_blob_to_r2(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"payload")
    md5 = store.put(src)

    with mock_aws():
        _make_bucket()
        store.push(md5)

        assert store.has_remote(md5) is True


def test_push_raises_when_blob_missing_locally(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        _make_bucket()
        with pytest.raises(FileNotFoundError, match="not in local CAS"):
            store.push("0" * 32)


def test_push_is_idempotent(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"payload")
    md5 = store.put(src)

    with mock_aws():
        _make_bucket()
        store.push(md5)
        store.push(md5)  # second push is a no-op
        assert store.has_remote(md5) is True


def test_pull_downloads_remote_blob_into_local_cas(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    payload = b"remote bytes"
    md5 = "abc" + "0" * 29

    with mock_aws():
        _make_bucket()
        boto3.client(
            "s3",
            aws_access_key_id="test_access",
            aws_secret_access_key="test_secret",
            region_name="us-east-1",
        ).put_object(
            Bucket="test-bucket",
            Key=f"files/md5/ab/c{'0' * 29}",
            Body=payload,
        )

        local = store.pull(md5)

        assert local.read_bytes() == payload
        assert local == cas_root / "files" / "md5" / "ab" / ("c" + "0" * 29)


def test_pull_raises_when_blob_missing_remotely(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        _make_bucket()
        with pytest.raises(FileNotFoundError, match="not in R2"):
            store.pull("0" * 32)
