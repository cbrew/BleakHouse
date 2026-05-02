"""Tests for run_cost upsert + idempotency."""
from __future__ import annotations

from pathlib import Path

from enrichment.expdb.store import Store


def test_upsert_run_cost_inserts_then_updates(tmp_db_path: Path) -> None:
    s = Store(tmp_db_path)
    s.init_schema()
    rid1 = s.upsert_run_cost(
        run_label="bh_trn_literary",
        stage="phase4",
        n_calls=10, cpu_s=120.5, wall_s=30.2,
        in_tok=0, cache_w_tok=0, cache_r_tok=0, out_tok=0,
        in_chars=15000, audio_ms=600_000,
        cost_usd=0.157, novel="bh",
    )
    # Re-upsert same (label, stage) — should update, not duplicate.
    rid2 = s.upsert_run_cost(
        run_label="bh_trn_literary",
        stage="phase4",
        n_calls=12, cpu_s=240.0, wall_s=60.0,
        in_tok=0, cache_w_tok=0, cache_r_tok=0, out_tok=0,
        in_chars=20000, audio_ms=800_000,
        cost_usd=0.200, novel="bh",
    )
    assert rid1 == rid2
    rows = s.list_run_costs("bh_trn_literary")
    assert len(rows) == 1
    r = rows[0]
    assert r["n_calls"] == 12
    assert r["cost_usd"] == 0.200


def test_multiple_stages_stay_separate(tmp_db_path: Path) -> None:
    s = Store(tmp_db_path)
    s.init_schema()
    s.upsert_run_cost(
        run_label="r1", stage="enrichment",
        n_calls=200, cpu_s=300.0, wall_s=300.0,
        in_tok=1000, cache_w_tok=50000, cache_r_tok=600000,
        out_tok=10000, in_chars=0, audio_ms=0,
        cost_usd=0.45, novel="motf",
    )
    s.upsert_run_cost(
        run_label="r1", stage="phase3",
        n_calls=7, cpu_s=80.0, wall_s=80.0,
        in_tok=30000, cache_w_tok=0, cache_r_tok=0,
        out_tok=15000, in_chars=0, audio_ms=0,
        cost_usd=0.32, novel="motf",
    )
    rows = s.list_run_costs("r1")
    assert len(rows) == 2
    by_stage = {r["stage"]: r for r in rows}
    assert by_stage["enrichment"]["cost_usd"] == 0.45
    assert by_stage["phase3"]["cost_usd"] == 0.32


def test_run_label_isolates_runs(tmp_db_path: Path) -> None:
    s = Store(tmp_db_path)
    s.init_schema()
    s.upsert_run_cost(
        run_label="r1", stage="phase4",
        n_calls=1, cpu_s=1.0, wall_s=1.0,
        in_tok=0, cache_w_tok=0, cache_r_tok=0, out_tok=0,
        in_chars=100, audio_ms=1000, cost_usd=0.001,
    )
    s.upsert_run_cost(
        run_label="r2", stage="phase4",
        n_calls=2, cpu_s=2.0, wall_s=2.0,
        in_tok=0, cache_w_tok=0, cache_r_tok=0, out_tok=0,
        in_chars=200, audio_ms=2000, cost_usd=0.002,
    )
    assert len(s.list_run_costs("r1")) == 1
    assert len(s.list_run_costs("r2")) == 1
    assert s.list_run_costs("r1")[0]["cost_usd"] == 0.001
    assert s.list_run_costs("r2")[0]["cost_usd"] == 0.002
