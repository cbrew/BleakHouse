"""Build data/content.db from precious run-dir + per-novel JSON artifacts.

Captures the seven precious-per-run artifacts plus per-novel character_arcs.
Stores raw JSON bytes (TEXT) — round-trip is byte-identical, which is the
trust contract for this first step. JSONB extraction can be added as a
generated column later without rewriting the import.

Schema:
    run_artifact   (run_id, kind) → payload + md5 + bytes
    novel_artifact (novel,  kind) → payload + md5 + bytes

Usage:
    uv run python scripts/build_content_db.py            # build (default db: data/content.db)
    uv run python scripts/build_content_db.py --verify   # round-trip check, no writes
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "content.db"
RUNS_DIR = REPO_ROOT / "data" / "runs"
NOVELS_DIR = REPO_ROOT / "data" / "novels"

# Per-run artifacts we capture. Keys are kind strings; values are paths
# relative to the run dir. Files that don't exist on a given run are skipped
# silently — phase2_5_host_briefs / phase3_teaser / shards_index are sparse.
RUN_KINDS: dict[str, str] = {
    "config":                "config.json",
    "phase0_segments":       "phase0_segments.json",
    "phase1_assignments":    "phase1_assignments.json",
    "phase2_plan":           "phase2_plan.json",
    "phase2_5_interviews":   "phase2_5_interviews.json",
    "phase2_5_host_briefs":  "phase2_5_host_briefs.json",
    "phase2_5_reading_list": "phase2_5_reading_list.json",
    "phase3_episode":        "phase3_episode.json",
    "phase3_teaser":         "phase3_teaser.json",
    "shards_index":          "audio/shards.json",
}

# Per-novel curated artefacts kept under `data/novels/<novel>/`.
# - character_arcs: clustering output (per-character chapter list).
#   BH uses Python DEFAULT_ARCS instead, so its character_arcs.json may
#   be absent — that's fine.
# - passages_enriched: LLM-tagged literary metadata per passage. Big
#   (~6 MB/novel × 19 = ~100 MB). Source-of-truth substrate for downstream
#   pipeline stages — irreplaceable LLM output.
# - clusters_characters / clusters_literary: clustering products used by
#   the segment planner.
NOVEL_KINDS: dict[str, str] = {
    "character_arcs":      "character_arcs.json",
    "passages_enriched":   "passages_enriched.json",
    "passages_contextual": "passages_contextual.json",
    "clusters_characters": "clusters_characters.json",
    "clusters_literary":   "clusters_literary.json",
}

# Per-novel arcs ('arcs' kind) live in Python source today
# (transport_podcast._BLEAK_HOUSE_ARCS + novel_prompts.get_novel_arcs).
# We capture them here so content.db is the source-of-truth target; the
# Python files remain the readers' source until those readers are migrated.
# The arcs payload schema is the JSON-friendly form of ArcDemand:
#   [{"name", "character", "demand", "require_field", "require_value",
#     "prefer_min_interest"}, ...]
ARCS_KIND = "arcs"


def _python_panels() -> dict[str, dict]:
    """Pull every panel's persona metadata out of Python source.

    Source: enrichment.axes.PANELS_TUPLE (panel id + display + expert
    names) joined with podcast_types.{DEFAULT_PERSONAS, ALTERNATIVE_PERSONAS}
    keyed by name. Skips voice_policy / speaking_style — those are TTS
    internals, not consumer-facing data. v2 will read this table directly
    instead of importing the Python dicts.
    """
    from enrichment.axes import PANELS_TUPLE  # type: ignore[import]
    from enrichment.personas import (
        ALTERNATIVE_PERSONAS,
        DEFAULT_PERSONAS,
    )
    by_name = {p.name: p for p in DEFAULT_PERSONAS}
    by_name.update({p.name: p for p in ALTERNATIVE_PERSONAS.values()})

    out: dict[str, dict] = {}
    for panel in PANELS_TUPLE:
        experts = []
        for ename in panel.experts:
            persona = by_name.get(ename)
            if persona is None:
                # A panel referencing a name with no persona is a config
                # bug worth surfacing loudly rather than silently skipping.
                raise KeyError(
                    f"Panel {panel.id!r} references expert {ename!r} "
                    f"with no matching ExpertPersona"
                )
            experts.append({
                "name": persona.name,
                "role": persona.role,
                "description": persona.description,
                "script_description": persona.script_description,
            })
        out[panel.id] = {
            "id": panel.id,
            "display": panel.display,
            "experts": experts,
        }
    return out


def _python_arcs() -> dict[str, list[dict]]:
    """Pull every novel's arcs out of Python source into JSON-shaped dicts.

    BH's arcs live in transport_podcast._BLEAK_HOUSE_ARCS as ArcDemand
    instances; the rest live in novel_prompts.get_novel_arcs as 6-tuples.
    """
    from enrichment.novel_prompts import get_novel_arcs  # type: ignore[import]
    from enrichment.transport_podcast import _BLEAK_HOUSE_ARCS  # type: ignore[import]

    fields = ("name", "character", "demand", "require_field",
              "require_value", "prefer_min_interest")

    out: dict[str, list[dict]] = {
        "bleak_house": [
            {f: getattr(arc, f) for f in fields} for arc in _BLEAK_HOUSE_ARCS
        ],
    }
    # get_novel_arcs returns [] for unknown keys, so probe each novel dir.
    for novel_dir in sorted(NOVELS_DIR.iterdir()):
        if not novel_dir.is_dir():
            continue
        novel = novel_dir.name
        if novel == "bleak_house":
            continue
        tuples = get_novel_arcs(novel)
        if not tuples:
            continue
        out[novel] = [dict(zip(fields, t)) for t in tuples]
    return out

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 2;

CREATE TABLE IF NOT EXISTS run_artifact (
    run_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    md5         TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    imported_at REAL NOT NULL,
    PRIMARY KEY (run_id, kind)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS novel_artifact (
    novel       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    md5         TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    imported_at REAL NOT NULL,
    PRIMARY KEY (novel, kind)
) STRICT, WITHOUT ROWID;

-- Per-panel persona metadata (name, role, descriptions).
-- Source-of-truth target: replaces the Python ALTERNATIVE_PERSONAS /
-- DEFAULT_PERSONAS dicts. Built from Python at content.db build time;
-- readers will migrate to this table separately.
CREATE TABLE IF NOT EXISTS panel_artifact (
    panel_id    TEXT NOT NULL PRIMARY KEY,
    payload     TEXT NOT NULL,
    md5         TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    imported_at REAL NOT NULL
) STRICT, WITHOUT ROWID;

-- Derived index: one row per run, axis values pulled from config.json
-- (canonicalised) and audio presence joined from shards_index /
-- audio_assets. Rebuilt on every build_content_db.py run; no precious
-- data, just a query convenience.
CREATE TABLE IF NOT EXISTS run_index (
    run_id      TEXT NOT NULL PRIMARY KEY,
    novel       TEXT NOT NULL,
    panel       TEXT NOT NULL,
    pipeline    TEXT NOT NULL,
    length      TEXT NOT NULL,
    hostprep    INTEGER NOT NULL,
    ref_tools   INTEGER NOT NULL,
    generator   TEXT NOT NULL,
    has_audio   INTEGER NOT NULL,
    rebuilt_at  REAL NOT NULL
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_run_index_novel_panel
    ON run_index(novel, panel);
CREATE INDEX IF NOT EXISTS idx_run_index_has_audio
    ON run_index(has_audio);
"""


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _extract_axes(config_payload: str) -> dict | None:
    """Pull axis values from a config.json payload, canonicalising on the way.

    Two on-disk shapes coexist: nested ('axes' block) and flat (axes at
    root, retrofit runs only). Returns None when the required fields are
    missing — caller decides whether to skip or default.
    """
    import json as _json
    from enrichment.axes import canonicalize_value, panel_for_experts  # type: ignore

    try:
        cfg = _json.loads(config_payload)
    except _json.JSONDecodeError:
        return None
    if not isinstance(cfg, dict):
        return None

    nested = cfg.get("axes")
    block: dict = nested if isinstance(nested, dict) else cfg
    novel = block.get("novel")
    pipeline = block.get("pipeline")
    if not novel or not pipeline:
        return None

    panel = block.get("panel")
    if not panel:
        # Retrofit runs sometimes lack a panel field — infer from experts.
        experts = cfg.get("experts") or block.get("experts") or []
        names: list[str] = [
            e["name"] for e in experts
            if isinstance(e, dict) and isinstance(e.get("name"), str)
        ]
        panel = panel_for_experts(names) or "unknown"

    def canon(name: str, raw: object, default: str) -> str:
        try:
            return canonicalize_value(name, raw)
        except (ValueError, KeyError):
            return default

    return {
        "novel":     canon("novel", novel, str(novel)),
        "pipeline":  canon("pipeline", pipeline, str(pipeline)),
        "panel":     str(panel),
        "length":    str(block.get("length") or "long"),
        "hostprep":  bool(block.get("hostprep", False)),
        "generator": str(block.get("generator") or "unknown"),
    }


def _rebuild_run_index(conn: sqlite3.Connection, now: float) -> int:
    """Wipe and rebuild run_index from current run_artifact rows.

    has_audio = shards_index row present. ref_tools = phase2_5_reading_list
    row present (matches the legacy expdb scan rule). Skips rows whose
    config payload doesn't yield novel + pipeline.
    """
    conn.execute("DELETE FROM run_index")

    # Pre-compute kind-presence sets for cheap joins.
    has_shards: set[str] = {
        r[0] for r in conn.execute(
            "SELECT run_id FROM run_artifact WHERE kind='shards_index'"
        )
    }
    has_reading_list: set[str] = {
        r[0] for r in conn.execute(
            "SELECT run_id FROM run_artifact "
            "WHERE kind='phase2_5_reading_list'"
        )
    }

    n = 0
    for row in conn.execute(
        "SELECT run_id, payload FROM run_artifact WHERE kind='config'"
    ):
        run_id, payload = row[0], row[1]
        axes = _extract_axes(payload)
        if axes is None:
            continue
        conn.execute(
            "INSERT INTO run_index"
            "(run_id, novel, panel, pipeline, length, hostprep,"
            " ref_tools, generator, has_audio, rebuilt_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, axes["novel"], axes["panel"], axes["pipeline"],
             axes["length"], int(axes["hostprep"]),
             int(run_id in has_reading_list), axes["generator"],
             int(run_id in has_shards), now),
        )
        n += 1
    return n


def build(db_path: Path) -> dict:
    """Import every precious artifact into content.db.

    Idempotent: re-running upserts; md5 changes detect silent edits.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _conn(db_path)
    init_schema(conn)

    n_run = 0
    n_novel = 0
    n_panel = 0
    skipped: list[str] = []
    now = time.time()

    conn.execute("BEGIN")
    try:
        for run_dir in sorted(RUNS_DIR.iterdir()):
            if not run_dir.is_dir() or run_dir.name.startswith("_"):
                continue
            run_id = run_dir.name
            for kind, relpath in RUN_KINDS.items():
                src = run_dir / relpath
                if not src.exists():
                    continue
                try:
                    text = src.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    skipped.append(f"{run_id}/{relpath}: {exc}")
                    continue
                conn.execute(
                    "INSERT INTO run_artifact(run_id, kind, payload, md5, bytes, imported_at)"
                    " VALUES(?,?,?,?,?,?)"
                    " ON CONFLICT(run_id, kind) DO UPDATE SET"
                    "   payload=excluded.payload,"
                    "   md5=excluded.md5,"
                    "   bytes=excluded.bytes,"
                    "   imported_at=excluded.imported_at",
                    (run_id, kind, text, _md5(text), len(text.encode("utf-8")), now),
                )
                n_run += 1

        for novel_dir in sorted(NOVELS_DIR.iterdir()):
            if not novel_dir.is_dir():
                continue
            novel = novel_dir.name
            for kind, relpath in NOVEL_KINDS.items():
                src = novel_dir / relpath
                if not src.exists():
                    continue
                try:
                    text = src.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    skipped.append(f"{novel}/{relpath}: {exc}")
                    continue
                conn.execute(
                    "INSERT INTO novel_artifact(novel, kind, payload, md5, bytes, imported_at)"
                    " VALUES(?,?,?,?,?,?)"
                    " ON CONFLICT(novel, kind) DO UPDATE SET"
                    "   payload=excluded.payload,"
                    "   md5=excluded.md5,"
                    "   bytes=excluded.bytes,"
                    "   imported_at=excluded.imported_at",
                    (novel, kind, text, _md5(text), len(text.encode("utf-8")), now),
                )
                n_novel += 1

        # Per-novel arcs (Python-sourced; no on-disk file). Stable JSON
        # serialization (sort_keys, indent=2) so re-imports are
        # byte-stable and md5 comparison detects real changes.
        import json
        for novel, arcs in _python_arcs().items():
            text = json.dumps(arcs, indent=2, ensure_ascii=False) + "\n"
            conn.execute(
                "INSERT INTO novel_artifact(novel, kind, payload, md5, bytes, imported_at)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(novel, kind) DO UPDATE SET"
                "   payload=excluded.payload,"
                "   md5=excluded.md5,"
                "   bytes=excluded.bytes,"
                "   imported_at=excluded.imported_at",
                (novel, ARCS_KIND, text, _md5(text),
                 len(text.encode("utf-8")), now),
            )
            n_novel += 1

        # Per-panel persona metadata, Python-sourced. Same byte-stability
        # property as arcs.
        for panel_id, panel_payload in _python_panels().items():
            text = json.dumps(panel_payload, indent=2, ensure_ascii=False) + "\n"
            conn.execute(
                "INSERT INTO panel_artifact"
                "(panel_id, payload, md5, bytes, imported_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(panel_id) DO UPDATE SET"
                "   payload=excluded.payload,"
                "   md5=excluded.md5,"
                "   bytes=excluded.bytes,"
                "   imported_at=excluded.imported_at",
                (panel_id, text, _md5(text),
                 len(text.encode("utf-8")), now),
            )
            n_panel += 1

        # Derived index. Built last so all the run_artifact rows we need
        # to join on are in place.
        n_index = _rebuild_run_index(conn, now)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {
        "run_artifacts": n_run,
        "novel_artifacts": n_novel,
        "panel_artifacts": n_panel,
        "run_index_rows": n_index,
        "skipped": skipped,
    }


def verify(db_path: Path) -> dict:
    """Round-trip check: every row in content.db must byte-match its source file.

    Catches truncation, encoding drift, and silent disk edits since import.
    """
    conn = _conn(db_path)
    mismatches: list[str] = []
    missing_on_disk: list[str] = []
    n_checked = 0

    for row in conn.execute("SELECT run_id, kind, payload, md5 FROM run_artifact"):
        relpath = RUN_KINDS.get(row["kind"])
        if relpath is None:
            mismatches.append(f"{row['run_id']}/{row['kind']}: unknown kind")
            continue
        src = RUNS_DIR / row["run_id"] / relpath
        if not src.exists():
            missing_on_disk.append(f"{row['run_id']}/{relpath}")
            continue
        on_disk = src.read_text(encoding="utf-8")
        if on_disk != row["payload"]:
            mismatches.append(f"{row['run_id']}/{row['kind']}: payload differs")
        elif _md5(row["payload"]) != row["md5"]:
            mismatches.append(f"{row['run_id']}/{row['kind']}: stored md5 wrong")
        n_checked += 1

    # Cache the regenerated arcs / panel payloads — Python source, not disk.
    import json
    arcs_expected = {
        novel: json.dumps(arcs, indent=2, ensure_ascii=False) + "\n"
        for novel, arcs in _python_arcs().items()
    }

    for row in conn.execute("SELECT novel, kind, payload, md5 FROM novel_artifact"):
        if row["kind"] == ARCS_KIND:
            expected = arcs_expected.get(row["novel"])
            if expected is None:
                mismatches.append(f"{row['novel']}/arcs: in DB but not in Python source")
                continue
            if expected != row["payload"]:
                mismatches.append(f"{row['novel']}/arcs: payload differs from Python source")
            elif _md5(row["payload"]) != row["md5"]:
                mismatches.append(f"{row['novel']}/arcs: stored md5 wrong")
            n_checked += 1
            continue

        relpath = NOVEL_KINDS.get(row["kind"])
        if relpath is None:
            mismatches.append(f"{row['novel']}/{row['kind']}: unknown kind")
            continue
        src = NOVELS_DIR / row["novel"] / relpath
        if not src.exists():
            missing_on_disk.append(f"{row['novel']}/{relpath}")
            continue
        on_disk = src.read_text(encoding="utf-8")
        if on_disk != row["payload"]:
            mismatches.append(f"{row['novel']}/{row['kind']}: payload differs")
        elif _md5(row["payload"]) != row["md5"]:
            mismatches.append(f"{row['novel']}/{row['kind']}: stored md5 wrong")
        n_checked += 1

    # Panel artifacts: regenerate from Python source, compare byte-for-byte.
    panels_expected = {
        pid: json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        for pid, payload in _python_panels().items()
    }
    for row in conn.execute("SELECT panel_id, payload, md5 FROM panel_artifact"):
        expected = panels_expected.get(row["panel_id"])
        if expected is None:
            mismatches.append(f"panel/{row['panel_id']}: in DB but not in Python source")
            continue
        if expected != row["payload"]:
            mismatches.append(f"panel/{row['panel_id']}: payload differs from Python source")
        elif _md5(row["payload"]) != row["md5"]:
            mismatches.append(f"panel/{row['panel_id']}: stored md5 wrong")
        n_checked += 1
    # Catch panels declared in Python that didn't make it into the DB.
    for pid in panels_expected:
        if not conn.execute(
            "SELECT 1 FROM panel_artifact WHERE panel_id=?", (pid,)
        ).fetchone():
            mismatches.append(f"panel/{pid}: in Python source but not in DB")

    conn.close()
    return {
        "checked": n_checked,
        "mismatches": mismatches,
        "missing_on_disk": missing_on_disk,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB,
                   help=f"DB path (default: {DEFAULT_DB.relative_to(REPO_ROOT)})")
    p.add_argument("--verify", action="store_true",
                   help="Skip import; verify existing DB matches disk")
    args = p.parse_args()

    if args.verify:
        if not args.db.exists():
            print(f"DB not found: {args.db}", file=sys.stderr)
            return 1
        out = verify(args.db)
        print(f"checked: {out['checked']}")
        if out["mismatches"]:
            print(f"MISMATCHES ({len(out['mismatches'])}):", file=sys.stderr)
            for m in out["mismatches"][:20]:
                print(f"  {m}", file=sys.stderr)
            return 2
        if out["missing_on_disk"]:
            print(f"missing on disk ({len(out['missing_on_disk'])}):", file=sys.stderr)
            for m in out["missing_on_disk"][:20]:
                print(f"  {m}", file=sys.stderr)
        print("round-trip: OK")
        return 0

    out = build(args.db)
    print(f"run_artifacts:   {out['run_artifacts']}")
    print(f"novel_artifacts: {out['novel_artifacts']}")
    print(f"panel_artifacts: {out['panel_artifacts']}")
    print(f"run_index_rows:  {out['run_index_rows']}")
    if out["skipped"]:
        print(f"skipped ({len(out['skipped'])}):")
        for s in out["skipped"][:20]:
            print(f"  {s}")
    print(f"db: {args.db} ({args.db.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
