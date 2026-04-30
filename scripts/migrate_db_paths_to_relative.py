"""One-shot migration: rewrite absolute paths in experiments.db to repo-relative.

The experiment ledger has historically stored a mix of absolute paths
(written from scripts that passed `str(absolute_path)`) and relative
paths. Absolute paths break the moment the repo moves — across machines,
into a Fly container, or to a Linux server. This script normalises every
path column so the DB ships with the data and works wherever the repo
lives.

Idempotent. Safe to run multiple times. Touches only path columns:

    hostprep_version.interviews_path
    hostprep_version.briefs_path
    script_version.path
    audio_artifact.path
    audio_artifact.audio_manifest_path

Usage:
    uv run python scripts/migrate_db_paths_to_relative.py
    uv run python scripts/migrate_db_paths_to_relative.py --dry-run
    uv run python scripts/migrate_db_paths_to_relative.py --db custom.db
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = REPO_ROOT / "data" / "experiments.db"

# (table, column) pairs to migrate.
TARGETS: tuple[tuple[str, str], ...] = (
    ("hostprep_version", "interviews_path"),
    ("hostprep_version", "briefs_path"),
    ("script_version", "path"),
    ("audio_artifact", "path"),
    ("audio_artifact", "audio_manifest_path"),
)


def to_repo_relative(path: str | None) -> str | None:
    if path is None or path == "":
        return path
    p = Path(path)
    if not p.is_absolute():
        return path
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        # Path is absolute but outside the repo — leave as-is and warn.
        return path


def migrate(db_path: Path, dry_run: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        for table, col in TARGETS:
            rows = conn.execute(
                f"SELECT id, {col} AS p FROM {table} WHERE {col} IS NOT NULL"
            ).fetchall()
            updates = []
            for r in rows:
                rel = to_repo_relative(r["p"])
                if rel is not None and rel != r["p"]:
                    updates.append((rel, r["id"]))
            counts[f"{table}.{col}"] = len(updates)
            if updates and not dry_run:
                conn.executemany(
                    f"UPDATE {table} SET {col}=? WHERE id=?", updates
                )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_DEFAULT,
                        help=f"experiments.db path (default: {DB_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="report changes without writing")
    args = parser.parse_args()

    counts = migrate(args.db, dry_run=args.dry_run)
    label = "would update" if args.dry_run else "updated"
    total = sum(counts.values())
    print(f"{label} {total} rows in {args.db}:")
    for k, n in counts.items():
        print(f"  {n:5} {k}")


if __name__ == "__main__":
    main()
