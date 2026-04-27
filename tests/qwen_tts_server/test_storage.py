from __future__ import annotations

from pathlib import Path

import pytest

from experiments.qwen_tts_server.state import JobStorage


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


def test_paths_are_under_job_dir(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    assert s.root == jobs_dir / "abc123"
    assert s.inputs == s.root / "inputs"
    assert s.refs == s.root / "refs"
    assert s.out == s.root / "out"
    assert s.log == s.root / "log.txt"


def test_create_makes_subdirs(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    assert s.inputs.is_dir()
    assert s.refs.is_dir()
    assert s.out.is_dir()


def test_save_input_writes_bytes(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    s.save_input("manifest.json", b'{"hello": 1}')
    assert (s.inputs / "manifest.json").read_bytes() == b'{"hello": 1}'


def test_result_path_resolves_within_out(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    (s.out / "episode.wav").write_bytes(b"RIFF...")
    assert s.result_path("episode.wav").read_bytes() == b"RIFF..."


def test_result_path_rejects_traversal(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    with pytest.raises(ValueError):
        s.result_path("../../etc/passwd")
    with pytest.raises(ValueError):
        s.result_path("/etc/passwd")
