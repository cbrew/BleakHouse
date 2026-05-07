"""Tests for scripts.cas_migrate — DVC → CAS one-shot migration.

Phase A (inventory) and Phase B (R2 verify) are read-only. Phase C (populate
local CAS) and Phase D (replacement manifests) are mutating; tests exercise
them against tmp_path-rooted CAS and tmp_path-rooted run dirs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import cas_migrate


# ---------------------------------------------------------------------------
# Phase A — parsers
# ---------------------------------------------------------------------------


def test_parse_dvc_outs_returns_dir_md5_and_path(tmp_path: Path) -> None:
    dvc = tmp_path / "classic.dvc"
    dvc.write_text(
        "outs:\n"
        "- md5: 624dbe3eec3d05df0da884076fd5f5e6.dir\n"
        "  size: 63755764\n"
        "  nfiles: 71\n"
        "  hash: md5\n"
        "  path: classic\n"
    )
    outs = cas_migrate.parse_dvc_outs(dvc)
    assert outs == [
        {
            "md5": "624dbe3eec3d05df0da884076fd5f5e6",
            "is_dir": True,
            "size": 63755764,
            "nfiles": 71,
            "path": "classic",
        }
    ]


def test_parse_dvc_outs_handles_plain_file(tmp_path: Path) -> None:
    dvc = tmp_path / "podcast.mp3.dvc"
    dvc.write_text(
        "outs:\n"
        "- md5: deadbeef00000000000000000000feed\n"
        "  size: 12345\n"
        "  hash: md5\n"
        "  path: podcast.mp3\n"
    )
    outs = cas_migrate.parse_dvc_outs(dvc)
    assert outs == [
        {
            "md5": "deadbeef00000000000000000000feed",
            "is_dir": False,
            "size": 12345,
            "nfiles": None,
            "path": "podcast.mp3",
        }
    ]


def test_collect_dvc_lock_mp3s_extracts_phase4_outs() -> None:
    lock_yaml = """\
schema: '2.0'
stages:
  phase4_audio@bh_trn_literary:
    cmd: foo
    outs:
    - path: data/runs/bh_trn_literary/audio/podcast.mp3
      hash: md5
      md5: aaaa1111bbbb2222cccc3333dddd4444
      size: 100
  phase4_audio@bh_trn_alternatives:
    cmd: bar
    outs:
    - path: data/runs/bh_trn_alternatives/audio/podcast.mp3
      hash: md5
      md5: 1111aaaa2222bbbb3333cccc4444dddd
      size: 200
"""
    entries = cas_migrate.collect_dvc_lock_mp3s(lock_yaml)
    assert entries == [
        {
            "run_id": "bh_trn_literary",
            "filename": "podcast.mp3",
            "path": "data/runs/bh_trn_literary/audio/podcast.mp3",
            "md5": "aaaa1111bbbb2222cccc3333dddd4444",
            "size": 100,
        },
        {
            "run_id": "bh_trn_alternatives",
            "filename": "podcast.mp3",
            "path": "data/runs/bh_trn_alternatives/audio/podcast.mp3",
            "md5": "1111aaaa2222bbbb3333cccc4444dddd",
            "size": 200,
        },
    ]


def test_collect_dvc_lock_mp3s_ignores_non_phase4_stages() -> None:
    lock_yaml = """\
stages:
  phase0_segment@bh:
    outs:
    - path: data/runs/bh/segments.json
      md5: ffff0000ffff0000ffff0000ffff0000
  phase4_audio@bh_trn_literary:
    outs:
    - path: data/runs/bh_trn_literary/audio/podcast.mp3
      md5: aaaa1111bbbb2222cccc3333dddd4444
"""
    entries = cas_migrate.collect_dvc_lock_mp3s(lock_yaml)
    assert len(entries) == 1
    assert entries[0]["filename"] == "podcast.mp3"


def test_collect_dvc_lock_mp3s_dedupes_paths() -> None:
    """Same out path appears in multiple stages — only one entry."""
    lock_yaml = """\
stages:
  phase4_audio@bh_trn_literary:
    outs:
    - path: data/runs/bh_trn_literary/audio/podcast.mp3
      md5: aaaa1111bbbb2222cccc3333dddd4444
  phase4_audio@bh_trn_alternatives_hostprep:
    outs:
    - path: data/runs/bh_trn_alternatives_hostprep/audio/podcast.mp3
      md5: 1111aaaa2222bbbb3333cccc4444dddd
    - path: data/runs/bh_trn_literary/audio/podcast.mp3
      md5: aaaa1111bbbb2222cccc3333dddd4444
"""
    entries = cas_migrate.collect_dvc_lock_mp3s(lock_yaml)
    paths = [e["path"] for e in entries]
    assert len(paths) == len(set(paths)), "duplicate paths leaked"
    assert len(entries) == 2


def test_expand_dir_listing_returns_per_file_md5s() -> None:
    listing_bytes = json.dumps(
        [
            {"md5": "0000aaaa0000aaaa0000aaaa0000aaaa", "relpath": "0000.mp3"},
            {"md5": "1111bbbb1111bbbb1111bbbb1111bbbb", "relpath": "0001.mp3"},
        ]
    ).encode()
    files = cas_migrate.expand_dir_listing(listing_bytes)
    assert files == [
        {"md5": "0000aaaa0000aaaa0000aaaa0000aaaa", "relpath": "0000.mp3"},
        {"md5": "1111bbbb1111bbbb1111bbbb1111bbbb", "relpath": "0001.mp3"},
    ]


# ---------------------------------------------------------------------------
# Phase B — verify R2 coverage
# ---------------------------------------------------------------------------


def test_verify_r2_coverage_returns_empty_misses_when_all_present() -> None:
    md5s = ["aa" + "0" * 30, "bb" + "0" * 30]
    hits, misses = cas_migrate.verify_r2_coverage(
        md5s, has_remote=lambda _md5: True
    )
    assert misses == set()
    assert hits == set(md5s)


def test_verify_r2_coverage_aborts_on_miss_by_default() -> None:
    md5s = ["aa" + "0" * 30, "bb" + "0" * 30]
    seen: set[str] = set()

    def has_remote(md5: str) -> bool:
        seen.add(md5)
        return md5.startswith("aa")

    with pytest.raises(RuntimeError, match=r"missing in R2"):
        cas_migrate.verify_r2_coverage(md5s, has_remote=has_remote)


def test_verify_r2_coverage_returns_misses_when_allowed() -> None:
    md5s = ["aa" + "0" * 30, "bb" + "0" * 30, "cc" + "0" * 30]
    hits, misses = cas_migrate.verify_r2_coverage(
        md5s,
        has_remote=lambda md5: not md5.startswith("bb"),
        allow_misses=True,
    )
    assert misses == {"bb" + "0" * 30}
    assert hits == {"aa" + "0" * 30, "cc" + "0" * 30}


# ---------------------------------------------------------------------------
# Phase C — populate local CAS
# ---------------------------------------------------------------------------


@pytest.fixture
def cas_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cas"
    root.mkdir()
    monkeypatch.setenv("BLEAKHOUSE_CAS_ROOT", str(root))
    return root


def _md5(payload: bytes) -> str:
    return hashlib.md5(payload, usedforsecurity=False).hexdigest()


def test_populate_local_cas_copies_via_md5(
    cas_root_env: Path, tmp_path: Path
) -> None:
    src = tmp_path / "0000.mp3"
    payload = b"audio bytes"
    src.write_bytes(payload)
    md5 = _md5(payload)

    populated, skipped = cas_migrate.populate_local_cas(
        [(md5, src)], dry_run=False
    )

    assert populated == 1
    assert skipped == 0
    blob = cas_root_env / "files" / "md5" / md5[:2] / md5[2:]
    assert blob.read_bytes() == payload


def test_populate_local_cas_is_idempotent(
    cas_root_env: Path, tmp_path: Path
) -> None:
    src = tmp_path / "0000.mp3"
    src.write_bytes(b"audio")
    md5 = _md5(b"audio")

    cas_migrate.populate_local_cas([(md5, src)], dry_run=False)
    populated, skipped = cas_migrate.populate_local_cas(
        [(md5, src)], dry_run=False
    )
    assert populated == 0
    assert skipped == 1


def test_populate_local_cas_raises_on_md5_mismatch(
    cas_root_env: Path, tmp_path: Path
) -> None:
    src = tmp_path / "0000.mp3"
    src.write_bytes(b"audio")
    wrong_md5 = "0" * 32

    with pytest.raises(RuntimeError, match="md5 mismatch"):
        cas_migrate.populate_local_cas([(wrong_md5, src)], dry_run=False)


def test_populate_local_cas_dry_run_does_not_write(
    cas_root_env: Path, tmp_path: Path
) -> None:
    src = tmp_path / "0000.mp3"
    src.write_bytes(b"audio")
    md5 = _md5(b"audio")

    populated, skipped = cas_migrate.populate_local_cas(
        [(md5, src)], dry_run=True
    )
    assert populated == 1
    assert skipped == 0
    blob = cas_root_env / "files" / "md5" / md5[:2] / md5[2:]
    assert not blob.exists()


# ---------------------------------------------------------------------------
# Phase D — replacement manifests
# ---------------------------------------------------------------------------


def test_write_audio_assets_writes_schema(tmp_path: Path) -> None:
    run_dir = tmp_path / "data" / "runs" / "bh_trn_literary"
    (run_dir / "audio").mkdir(parents=True)
    legacy = [
        {"filename": "podcast.mp3", "md5": "aaaa" + "0" * 28},
        {"filename": "podcast_qwen.mp3", "md5": "bbbb" + "0" * 28},
    ]

    out = cas_migrate.write_audio_assets(run_dir, legacy, dry_run=False)

    assert out == run_dir / "audio" / "assets.json"
    written = json.loads(out.read_text())
    assert written == {
        "schema_version": 1,
        "assets": {
            "podcast.mp3": "aaaa" + "0" * 28,
            "podcast_qwen.mp3": "bbbb" + "0" * 28,
        },
    }


def test_write_audio_assets_dry_run_does_not_write(tmp_path: Path) -> None:
    run_dir = tmp_path / "data" / "runs" / "bh_trn_literary"
    (run_dir / "audio").mkdir(parents=True)
    out = cas_migrate.write_audio_assets(
        run_dir, [{"filename": "podcast.mp3", "md5": "aa" + "0" * 30}], dry_run=True
    )
    assert out == run_dir / "audio" / "assets.json"
    assert not out.exists()


def test_rename_dvc_hash_in_manifest_renames_key(tmp_path: Path) -> None:
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "bh_trn_literary",
                "stages": {
                    "phase4_audio": {
                        "fresh": True,
                        "dvc_hash": "ea0b3082baa072eed50612e8fcd68fd8",
                    },
                },
                "audio_variants": [
                    {"name": "classic", "dvc_hash": "abc" + "0" * 29}
                ],
            }
        )
    )

    changed = cas_migrate.rename_dvc_hash_in_manifest(manifest, dry_run=False)

    assert changed is True
    written = json.loads(manifest.read_text())
    assert "dvc_hash" not in json.dumps(written)
    assert written["stages"]["phase4_audio"]["md5"] == (
        "ea0b3082baa072eed50612e8fcd68fd8"
    )
    assert written["audio_variants"][0]["md5"] == "abc" + "0" * 29


def test_rename_dvc_hash_in_manifest_idempotent(tmp_path: Path) -> None:
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "stages": {
                    "phase4_audio": {"md5": "abc" + "0" * 29},
                }
            }
        )
    )
    assert (
        cas_migrate.rename_dvc_hash_in_manifest(manifest, dry_run=False) is False
    )


def test_rename_dvc_hash_dry_run_does_not_write(tmp_path: Path) -> None:
    manifest = tmp_path / "run_manifest.json"
    original = {
        "stages": {"phase4_audio": {"dvc_hash": "abc" + "0" * 29}},
    }
    manifest.write_text(json.dumps(original))
    changed = cas_migrate.rename_dvc_hash_in_manifest(manifest, dry_run=True)
    assert changed is True
    assert json.loads(manifest.read_text()) == original


def test_verify_shards_manifest_passes_when_md5s_match(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "audio"
    audio.mkdir()
    expected = ["aa" + "0" * 30, "bb" + "0" * 30]
    (audio / "shards.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "shards": [
                    {"file": "0000.mp3", "md5": expected[0]},
                    {"file": "0001.mp3", "md5": expected[1]},
                ],
            }
        )
    )
    cas_migrate.verify_shards_manifest(audio.parent, expected_md5s=set(expected))


# ---------------------------------------------------------------------------
# DVC cache resolution + Phase A end-to-end
# ---------------------------------------------------------------------------


def test_resolve_dvc_cache_dir_reads_config_local(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".dvc").mkdir(parents=True)
    (repo / ".dvc" / "config").write_text(
        "[core]\n    remote = r2\n"
    )
    (repo / ".dvc" / "config.local").write_text(
        "[cache]\n    dir = /Volumes/External/dvc-cache\n"
    )
    assert cas_migrate.resolve_dvc_cache_dir(repo) == Path(
        "/Volumes/External/dvc-cache"
    )


def test_resolve_dvc_cache_dir_defaults_when_unset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".dvc").mkdir(parents=True)
    (repo / ".dvc" / "config").write_text("[core]\n    remote = r2\n")
    assert cas_migrate.resolve_dvc_cache_dir(repo) == repo / ".dvc" / "cache"


def test_build_inventory_combines_dvc_files_and_dvc_lock(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runs = repo / "data" / "runs" / "bh_trn_literary" / "audio" / "shards"
    runs.mkdir(parents=True)
    (runs / "classic.dvc").write_text(
        "outs:\n"
        "- md5: 624dbe3eec3d05df0da884076fd5f5e6.dir\n"
        "  size: 100\n"
        "  nfiles: 2\n"
        "  hash: md5\n"
        "  path: classic\n"
    )
    (repo / "dvc.lock").write_text(
        "stages:\n"
        "  phase4_audio@bh_trn_literary:\n"
        "    outs:\n"
        "    - path: data/runs/bh_trn_literary/audio/podcast.mp3\n"
        "      md5: aaaa1111bbbb2222cccc3333dddd4444\n"
        "      size: 50\n"
    )

    listings = {
        "624dbe3eec3d05df0da884076fd5f5e6": json.dumps(
            [
                {"md5": "1111" + "0" * 28, "relpath": "0000.mp3"},
                {"md5": "2222" + "0" * 28, "relpath": "0001.mp3"},
            ]
        ).encode()
    }
    inv = cas_migrate.build_inventory(
        repo, fetch_dir_listing=lambda md5: listings[md5]
    )

    assert inv["summary"] == {
        "dvc_shard_dirs": 1,
        "shard_files_total": 2,
        "legacy_mp3s_total": 1,
        "unique_md5s": 3,  # 2 shard files + 1 legacy mp3
    }
    shard = inv["dvc_shards"][0]
    assert shard["run_id"] == "bh_trn_literary"
    assert shard["profile"] == "classic"
    assert shard["dir_md5"] == "624dbe3eec3d05df0da884076fd5f5e6"
    assert {f["md5"] for f in shard["files"]} == {
        "1111" + "0" * 28,
        "2222" + "0" * 28,
    }
    assert inv["legacy_mp3s"][0]["md5"] == "aaaa1111bbbb2222cccc3333dddd4444"


def test_verify_shards_manifest_raises_on_md5_drift(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "shards.json").write_text(
        json.dumps(
            {"shards": [{"file": "0000.mp3", "md5": "aa" + "0" * 30}]}
        )
    )
    with pytest.raises(RuntimeError, match="shards.json drift"):
        cas_migrate.verify_shards_manifest(
            audio.parent, expected_md5s={"cc" + "0" * 30}
        )
