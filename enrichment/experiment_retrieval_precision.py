"""Experiment 3: Retrieval Precision Against Enrichment Fields.

Measures how well different retrieval strategies recover passages with
expected enrichment properties.  Four strategies are compared:
  (a) Vector only — pure embedding similarity
  (b) Metadata only — filter enrichment fields, no vector search
  (c) Hybrid — vector search with metadata filter clause
  (d) Vector + re-rank — vector top-50, re-ranked by property match count

Each probe query specifies expected enrichment properties; precision is the
fraction of top-k results matching ALL expected properties.

Usage:
    uv run python -m enrichment.experiment_retrieval_precision
"""

import json
import logging
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DB_PATH = DATA_DIR / "bleak_house_vectors"
TABLE_NAME = "passages"
INPUT_PATH = DATA_DIR / "passages_enriched.json"
OUTPUT_PATH = DATA_DIR / "experiment_retrieval_precision.json"

K_VALUES = [10, 20]
RERANK_POOL = 50


# ---------------------------------------------------------------------------
# Probe queries
# ---------------------------------------------------------------------------


@dataclass
class ProbeQuery:
    """A retrieval probe with expected enrichment properties.

    Expected value semantics:
      - str fields: exact match (e.g. narrator="esther")
      - prov_* "strong": field value must be "strong"
      - prov_* "not_none": field value must not be "none"
      - interest_score (int): minimum threshold
      - characters_present (list[str]): at least one listed character present
      - plot_function (str): exact match
      - emotional_register (list[str]): at least one listed register present
      - quotability (str): exact match
    """

    query: str
    expected: dict[str, str | int | list[str]]
    description: str = ""


PROBE_QUERIES: list[ProbeQuery] = [
    # --- Atmosphere / setting ---
    ProbeQuery(
        query="fog and atmosphere in London",
        expected={"prov_atmosphere_setting": "strong"},
        description="iconic London fog passages",
    ),
    ProbeQuery(
        query="dark Gothic mood at Chesney Wold",
        expected={
            "prov_atmosphere_setting": "strong",
            "emotional_register": ["gothic"],
        },
        description="Gothic atmosphere at Chesney Wold",
    ),
    ProbeQuery(
        query="pastoral countryside scenes away from London",
        expected={
            "prov_atmosphere_setting": "not_none",
            "emotional_register": ["pastoral"],
        },
        description="pastoral settings",
    ),
    # --- Narrator ---
    ProbeQuery(
        query="Esther's feelings about her identity",
        expected={
            "narrator": "esther",
            "prov_character_development": "strong",
        },
        description="Esther's first-person self-reflection",
    ),
    ProbeQuery(
        query="Esther describes her friendships and affections",
        expected={
            "narrator": "esther",
            "emotional_register": ["tender"],
        },
        description="Esther's tender narration",
    ),
    ProbeQuery(
        query="the omniscient narrator surveys the scene",
        expected={"narrator": "omniscient"},
        description="third-person omniscient voice",
    ),
    # --- Social critique ---
    ProbeQuery(
        query="satirical commentary on the legal system",
        expected={
            "prov_social_critique": "strong",
            "prov_humor_entertainment": "strong",
        },
        description="satire of Chancery and the law",
    ),
    ProbeQuery(
        query="Dickens attacks poverty and institutional failure",
        expected={
            "prov_social_critique": "strong",
            "prov_thematic_depth": "strong",
        },
        description="social critique with thematic weight",
    ),
    ProbeQuery(
        query="commentary on Victorian class and society",
        expected={"prov_social_critique": "not_none"},
        description="any social critique",
    ),
    # --- Quotability ---
    ProbeQuery(
        query="quotable passages about Chancery",
        expected={"quotability": "strong"},
        description="memorable lines about the court",
    ),
    ProbeQuery(
        query="beautiful memorable prose worth reading aloud",
        expected={"quotability": "strong", "interest_score": 4},
        description="high-quotability high-interest passages",
    ),
    # --- Plot function ---
    ProbeQuery(
        query="a dramatic turning point or revelation",
        expected={"plot_function": "climax"},
        description="climactic moments",
    ),
    ProbeQuery(
        query="a startling secret is revealed",
        expected={"plot_function": "revelation"},
        description="revelation passages",
    ),
    ProbeQuery(
        query="characters talking to each other in conversation",
        expected={"plot_function": "dialogue"},
        description="dialogue-driven passages",
    ),
    ProbeQuery(
        query="detailed description of a place or person",
        expected={"plot_function": "description"},
        description="descriptive passages",
    ),
    # --- Emotional register ---
    ProbeQuery(
        query="comic scenes and humorous writing",
        expected={"emotional_register": ["comic"]},
        description="comic passages",
    ),
    ProbeQuery(
        query="tragic and sorrowful events",
        expected={"emotional_register": ["tragic"]},
        description="tragic passages",
    ),
    ProbeQuery(
        query="tense suspenseful moments of uncertainty",
        expected={"emotional_register": ["suspenseful"]},
        description="suspenseful passages",
    ),
    ProbeQuery(
        query="satirical ironic tone mocking institutions",
        expected={
            "emotional_register": ["satirical"],
            "prov_social_critique": "not_none",
        },
        description="satirical register with social critique",
    ),
    # --- Character presence ---
    ProbeQuery(
        query="Richard Carstone and Jarndyce and Jarndyce",
        expected={"characters_present": ["Richard", "Richard Carstone"]},
        description="Richard Carstone passages",
    ),
    ProbeQuery(
        query="Lady Dedlock's secret and her past",
        expected={"characters_present": ["Lady Dedlock", "Dedlock"]},
        description="Lady Dedlock passages",
    ),
    ProbeQuery(
        query="Mr Tulkinghorn investigating and scheming",
        expected={"characters_present": ["Tulkinghorn", "Mr Tulkinghorn"]},
        description="Tulkinghorn passages",
    ),
    ProbeQuery(
        query="Jo the crossing sweeper and his suffering",
        expected={
            "characters_present": ["Jo"],
            "prov_social_critique": "not_none",
        },
        description="Jo with social critique",
    ),
    # --- Interest score thresholds ---
    ProbeQuery(
        query="the most important and interesting moments in the novel",
        expected={"interest_score": 5},
        description="top interest score passages",
    ),
    ProbeQuery(
        query="notable passages worth discussing on a podcast",
        expected={"interest_score": 4},
        description="high interest passages",
    ),
    # --- Thematic depth ---
    ProbeQuery(
        query="the theme of justice and injustice",
        expected={"prov_thematic_depth": "strong"},
        description="thematically deep passages",
    ),
    ProbeQuery(
        query="identity and self-discovery in the novel",
        expected={
            "prov_thematic_depth": "not_none",
            "prov_character_development": "not_none",
        },
        description="identity themes with character development",
    ),
    # --- Narrative technique ---
    ProbeQuery(
        query="literary technique foreshadowing and irony",
        expected={"prov_narrative_technique": "strong"},
        description="notable literary technique",
    ),
    ProbeQuery(
        query="symbolic imagery and metaphor in the prose",
        expected={
            "prov_narrative_technique": "not_none",
            "prov_atmosphere_setting": "not_none",
        },
        description="technique with atmosphere",
    ),
    # --- Combined constraints ---
    ProbeQuery(
        query="Esther narrates a climactic scene with strong character development",
        expected={
            "narrator": "esther",
            "prov_character_development": "strong",
            "interest_score": 3,
        },
        description="Esther + character development + high interest",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def git_short_hash() -> str:
    """Return the short git hash of HEAD, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def make_timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_enrichment_lookup(path: Path) -> dict[str, dict]:
    """Build passage_id -> enrichment dict from passages_enriched.json."""
    raw = json.loads(path.read_text())
    lookup: dict[str, dict] = {}
    for p in raw:
        if p.get("enrichment"):
            lookup[p["passage_id"]] = p["enrichment"]
    return lookup


def passage_matches(enrichment: dict, expected: dict[str, str | int | list[str]]) -> bool:
    """Check whether a single passage's enrichment matches ALL expected properties."""
    for field_name, expected_val in expected.items():
        # --- characters_present: at least one listed character must appear ---
        if field_name == "characters_present":
            chars = enrichment.get("characters_present", [])
            chars_lower = [c.lower() for c in chars]
            assert isinstance(expected_val, list)
            if not any(
                any(ev.lower() in cl for cl in chars_lower)
                for ev in expected_val
            ):
                return False

        # --- emotional_register: at least one listed register present ---
        elif field_name == "emotional_register":
            registers = enrichment.get("emotional_register", [])
            assert isinstance(expected_val, list)
            if not any(er in registers for er in expected_val):
                return False

        # --- interest_score: minimum threshold ---
        elif field_name == "interest_score":
            score = enrichment.get("interest_score", 0)
            assert isinstance(expected_val, int)
            if score < expected_val:
                return False

        # --- prov_* and other string fields ---
        elif isinstance(expected_val, str):
            actual = enrichment.get(field_name, "none")
            if expected_val == "not_none":
                if actual == "none":
                    return False
            elif expected_val == "strong":
                if actual != "strong":
                    return False
            else:
                # Exact match (narrator, plot_function, quotability, etc.)
                if actual != expected_val:
                    return False

    return True


def count_matching_properties(enrichment: dict, expected: dict[str, str | int | list[str]]) -> int:
    """Count how many expected properties a passage matches (for re-ranking)."""
    count = 0
    for field_name, expected_val in expected.items():
        if field_name == "characters_present":
            chars = enrichment.get("characters_present", [])
            chars_lower = [c.lower() for c in chars]
            assert isinstance(expected_val, list)
            if any(any(ev.lower() in cl for cl in chars_lower) for ev in expected_val):
                count += 1
        elif field_name == "emotional_register":
            registers = enrichment.get("emotional_register", [])
            assert isinstance(expected_val, list)
            if any(er in registers for er in expected_val):
                count += 1
        elif field_name == "interest_score":
            score = enrichment.get("interest_score", 0)
            assert isinstance(expected_val, int)
            if score >= expected_val:
                count += 1
        elif isinstance(expected_val, str):
            actual = enrichment.get(field_name, "none")
            if expected_val == "not_none":
                if actual != "none":
                    count += 1
            elif expected_val == "strong":
                if actual == "strong":
                    count += 1
            else:
                if actual == expected_val:
                    count += 1
    return count


def build_lancedb_filter(expected: dict[str, str | int | list[str]]) -> str | None:
    """Build a LanceDB SQL WHERE clause from expected properties.

    Only includes fields that exist as columns in the LanceDB table:
    narrator, interest_score.  Other fields (prov_*, plot_function, etc.)
    are in the enrichment JSON but not in the LanceDB table, so they
    cannot be used in WHERE clauses.
    """
    clauses: list[str] = []
    if "narrator" in expected:
        val = expected["narrator"]
        if isinstance(val, str) and val not in ("not_none",):
            clauses.append(f"narrator = '{val}'")
    if "interest_score" in expected:
        val = expected["interest_score"]
        if isinstance(val, int):
            clauses.append(f"interest_score >= {val}")
    return " AND ".join(clauses) if clauses else None


# ---------------------------------------------------------------------------
# Retrieval strategies
# ---------------------------------------------------------------------------


def strategy_vector_only(
    table: lancedb.table.Table,  # type: ignore[name-defined]
    query: str,
    k: int,
) -> list[str]:
    """(a) Pure vector search, return top-k passage_ids."""
    results = table.search(query, query_type="vector").limit(k).to_pandas()
    return results["passage_id"].tolist()


def strategy_metadata_only(
    enrichment_lookup: dict[str, dict],
    all_passage_ids: list[str],
    expected: dict[str, str | int | list[str]],
    k: int,
) -> list[str]:
    """(b) Filter passages_enriched.json by expected properties (no vector search).

    Returns first k matching passage_ids in chapter order (which is the
    order they appear in the enrichment file).
    """
    matching: list[str] = []
    for pid in all_passage_ids:
        enr = enrichment_lookup.get(pid)
        if enr is None:
            continue
        if passage_matches(enr, expected):
            matching.append(pid)
            if len(matching) >= k:
                break
    return matching


def strategy_hybrid(
    table: lancedb.table.Table,  # type: ignore[name-defined]
    query: str,
    expected: dict[str, str | int | list[str]],
    k: int,
) -> list[str]:
    """(c) Vector search with LanceDB metadata filter.

    Only filters on fields available in the LanceDB table (narrator,
    interest_score).  If no filterable fields exist in expected, falls
    back to pure vector search.
    """
    search = table.search(query, query_type="vector")
    filter_clause = build_lancedb_filter(expected)
    if filter_clause:
        search = search.where(filter_clause)
    results = search.limit(k).to_pandas()
    return results["passage_id"].tolist()


def strategy_vector_rerank(
    table: lancedb.table.Table,  # type: ignore[name-defined]
    query: str,
    expected: dict[str, str | int | list[str]],
    enrichment_lookup: dict[str, dict],
    k: int,
) -> list[str]:
    """(d) Vector search top-50, re-rank by enrichment property match count.

    Ties in match count are broken by original vector rank (lower distance
    first).
    """
    results = table.search(query, query_type="vector").limit(RERANK_POOL).to_pandas()
    pids = results["passage_id"].tolist()

    scored: list[tuple[int, int, str]] = []
    for rank, pid in enumerate(pids):
        enr = enrichment_lookup.get(pid, {})
        match_count = count_matching_properties(enr, expected)
        # Sort by: match_count DESC, then original rank ASC
        scored.append((-match_count, rank, pid))

    scored.sort()
    return [pid for _, _, pid in scored[:k]]


# ---------------------------------------------------------------------------
# Precision computation
# ---------------------------------------------------------------------------


def compute_precision(
    result_ids: list[str],
    expected: dict[str, str | int | list[str]],
    enrichment_lookup: dict[str, dict],
) -> float:
    """Fraction of result passage_ids whose enrichment matches ALL expected properties."""
    if not result_ids:
        return 0.0
    match_count = 0
    for pid in result_ids:
        enr = enrichment_lookup.get(pid)
        if enr is not None and passage_matches(enr, expected):
            match_count += 1
    return match_count / len(result_ids)


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


STRATEGY_NAMES = ["vector_only", "metadata_only", "hybrid", "vector_rerank"]


def run_experiment(
    table: lancedb.table.Table,  # type: ignore[name-defined]
    enrichment_lookup: dict[str, dict],
    all_passage_ids: list[str],
) -> dict:
    """Run all probe queries against all strategies at all k values."""
    results: dict = {
        "queries": [],
        "summary": {},
    }

    # Accumulators: strategy -> k -> list of precisions
    precision_accum: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for qi, probe in enumerate(PROBE_QUERIES):
        logger.info(
            "Query %d/%d: %s",
            qi + 1,
            len(PROBE_QUERIES),
            probe.query[:60],
        )

        query_result: dict = {
            "query": probe.query,
            "description": probe.description,
            "expected": {
                k: v if not isinstance(v, list) else v
                for k, v in probe.expected.items()
            },
            "strategies": {},
        }

        for k in K_VALUES:
            k_results: dict[str, dict] = {}

            # (a) Vector only
            pids_a = strategy_vector_only(table, probe.query, k)
            prec_a = compute_precision(pids_a, probe.expected, enrichment_lookup)
            k_results["vector_only"] = {
                "precision": round(prec_a, 4),
                "n_results": len(pids_a),
                "passage_ids": pids_a,
            }
            precision_accum["vector_only"][k].append(prec_a)

            # (b) Metadata only
            pids_b = strategy_metadata_only(
                enrichment_lookup, all_passage_ids, probe.expected, k
            )
            prec_b = compute_precision(pids_b, probe.expected, enrichment_lookup)
            k_results["metadata_only"] = {
                "precision": round(prec_b, 4),
                "n_results": len(pids_b),
                "passage_ids": pids_b,
            }
            precision_accum["metadata_only"][k].append(prec_b)

            # (c) Hybrid
            pids_c = strategy_hybrid(table, probe.query, probe.expected, k)
            prec_c = compute_precision(pids_c, probe.expected, enrichment_lookup)
            k_results["hybrid"] = {
                "precision": round(prec_c, 4),
                "n_results": len(pids_c),
                "passage_ids": pids_c,
            }
            precision_accum["hybrid"][k].append(prec_c)

            # (d) Vector + re-rank
            pids_d = strategy_vector_rerank(
                table, probe.query, probe.expected, enrichment_lookup, k
            )
            prec_d = compute_precision(pids_d, probe.expected, enrichment_lookup)
            k_results["vector_rerank"] = {
                "precision": round(prec_d, 4),
                "n_results": len(pids_d),
                "passage_ids": pids_d,
            }
            precision_accum["vector_rerank"][k].append(prec_d)

            query_result["strategies"][f"k={k}"] = k_results

            logger.info(
                "  k=%d  vector=%.2f  metadata=%.2f  hybrid=%.2f  rerank=%.2f",
                k,
                prec_a,
                prec_b,
                prec_c,
                prec_d,
            )

        results["queries"].append(query_result)

    # Compute summary: mean precision per strategy per k
    summary: dict[str, dict[str, float]] = {}
    for strategy in STRATEGY_NAMES:
        summary[strategy] = {}
        for k in K_VALUES:
            vals = precision_accum[strategy][k]
            mean_prec = float(np.mean(vals)) if vals else 0.0
            summary[strategy][f"k={k}"] = round(mean_prec, 4)
    results["summary"] = summary

    return results


def write_report(results: dict, tag: str) -> Path:
    """Write a human-readable summary report."""
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"retrieval_precision_{tag}.txt"

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Experiment 3: Retrieval Precision Against Enrichment Fields")
    lines.append(f"Tag: {tag}")
    lines.append(f"Probe queries: {len(PROBE_QUERIES)}")
    lines.append(f"k values: {K_VALUES}")
    lines.append(f"Re-rank pool: {RERANK_POOL}")
    lines.append("=" * 78)
    lines.append("")

    # Summary table
    lines.append("SUMMARY: Mean Precision by Strategy")
    lines.append("-" * 50)
    header = f"{'Strategy':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>8}"
    lines.append(header)
    lines.append("-" * 50)

    summary = results["summary"]
    for strategy in STRATEGY_NAMES:
        row = f"{strategy:<20}"
        for k in K_VALUES:
            val = summary[strategy].get(f"k={k}", 0.0)
            row += f"  {val:>8.4f}"
        lines.append(row)
    lines.append("-" * 50)
    lines.append("")

    # Per-query breakdown
    lines.append("PER-QUERY BREAKDOWN")
    lines.append("=" * 78)
    for qi, qr in enumerate(results["queries"]):
        lines.append(f"\n[{qi + 1}] {qr['query']}")
        lines.append(f"    Description: {qr['description']}")
        lines.append(f"    Expected: {qr['expected']}")
        for k_label, strategies in qr["strategies"].items():
            parts = []
            for strategy in STRATEGY_NAMES:
                s = strategies[strategy]
                parts.append(f"{strategy}={s['precision']:.2f}({s['n_results']})")
            lines.append(f"    {k_label}: {', '.join(parts)}")

    lines.append("")
    lines.append("=" * 78)

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text)
    return report_path


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv()

    tag = f"{make_timestamp()}_{git_short_hash()}"
    logger.info("Experiment 3: Retrieval Precision Against Enrichment Fields")
    logger.info("Tag: %s", tag)

    # Load enrichment data
    logger.info("Loading enrichment data from %s", INPUT_PATH)
    enrichment_lookup = load_enrichment_lookup(INPUT_PATH)
    logger.info("Enrichment lookup: %d passages", len(enrichment_lookup))

    # Ordered passage_ids for metadata-only retrieval (chapter order)
    raw = json.loads(INPUT_PATH.read_text())
    all_passage_ids = [p["passage_id"] for p in raw if p.get("enrichment")]
    logger.info("Ordered passage IDs: %d", len(all_passage_ids))

    # Connect to LanceDB
    logger.info("Connecting to LanceDB at %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))
    table = db.open_table(TABLE_NAME)
    logger.info("LanceDB table '%s' ready", TABLE_NAME)

    # Run experiment
    results = run_experiment(table, enrichment_lookup, all_passage_ids)

    # Save JSON results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    logger.info("Saved results to %s", OUTPUT_PATH)

    # Save human-readable report
    report_path = write_report(results, tag)
    logger.info("Saved report to %s", report_path)

    # Print summary
    logger.info("\n--- Summary ---")
    for strategy in STRATEGY_NAMES:
        vals = results["summary"][strategy]
        parts = [f"{kl}={v:.4f}" for kl, v in vals.items()]
        logger.info("  %-20s %s", strategy, "  ".join(parts))

    logger.info("\nDone.")


if __name__ == "__main__":
    main()
