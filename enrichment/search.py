"""CLI search interface for contextual passage retrieval.

Usage:
    uv run python -m enrichment.search "What is the fog about?" [--top-k 10]
    uv run python -m enrichment.search "Esther's childhood" --narrator first_person
    uv run python -m enrichment.search "Jarndyce" --chapter c1 --min-interest 3
"""

import argparse
import logging
from pathlib import Path

import lancedb
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/bleak_house_vectors")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Search Bleak House passages")
    parser.add_argument("query", type=str, help="Search query")
    parser.add_argument(
        "--top-k", type=int, default=10, help="Number of results (default: 10)"
    )
    parser.add_argument("--narrator", type=str, help="Filter by narrator")
    parser.add_argument("--chapter", type=str, help="Filter by chapter_id")
    parser.add_argument(
        "--min-interest", type=int, help="Minimum interest score"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help=f"LanceDB path (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    load_dotenv()

    db = lancedb.connect(args.db_path)
    table = db.open_table("passages")

    search = table.search(args.query, query_type="vector")

    # Build where clause from filters
    filters: list[str] = []
    if args.narrator:
        filters.append(f"narrator = '{args.narrator}'")
    if args.chapter:
        filters.append(f"chapter_id = '{args.chapter}'")
    if args.min_interest is not None:
        filters.append(f"interest_score >= {args.min_interest}")

    if filters:
        search = search.where(" AND ".join(filters))

    results = search.limit(args.top_k).to_pandas()

    if results.empty:
        print("No results found.")
        return

    print(f"\n{'='*80}")
    print(f"Query: {args.query}")
    print(f"Results: {len(results)}")
    print(f"{'='*80}\n")

    for _, row in results.iterrows():
        score = row.get("_distance", "?")
        print(f"--- {row['passage_id']} (score: {score:.4f}) ---")
        print(f"  Chapter: {row['chapter_id']} — {row['chapter_title']}")
        print(f"  Narrator: {row['narrator']} | Interest: {row['interest_score']}")
        if row.get("themes"):
            print(f"  Themes: {row['themes']}")
        if row.get("context"):
            ctx = row["context"]
            print(f"  Context: {ctx[:120]}{'...' if len(ctx) > 120 else ''}")
        text = row["text"]
        print(f"  Text: {text[:200]}{'...' if len(text) > 200 else ''}")
        print()


if __name__ == "__main__":
    main()
