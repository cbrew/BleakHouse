#!/usr/bin/env bash
# Onboard a new novel end-to-end. Idempotent — each step skips if its
# output is already on disk. Stop on first failure (set -e).
#
# Usage:
#   bash scripts/add_novel.sh <novel_id>
#
#   <novel_id> is the long form (e.g. mrs_dalloway, oliver_twist), as
#   registered in enrichment/axes.py:NOVELS[].id and the data/novels/
#   directory layout.
#
# Prerequisites (manual; the script verifies they are in place):
#   - Novel registered in enrichment/axes.py NOVELS tuple
#   - Novel registered in enrichment/segment_novel.py NOVELS dict (gutenberg_id, html_filename)
#   - Novel registered in enrichment/novel_prompts.py NOVEL_CONFIGS + ARCS
#
# Wall-clock: ~1-2 hours for a typical Victorian novel (mostly batch wait
# time for Phase 0 enrichment + passage contexts).

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <novel_id>" >&2
    echo "  e.g. $0 oliver_twist" >&2
    exit 2
fi

NOVEL="$1"
NOVEL_DIR="data/novels/${NOVEL}"

# Step 0: Verify the novel is registered in all three places.
uv run python <<PY
from enrichment.axes import NOVEL_IDS
from enrichment.segment_novel import NOVELS as SEGMENT_NOVELS
from enrichment.novel_prompts import NOVEL_CONFIGS

novel = "${NOVEL}"
errors = []
if novel not in NOVEL_IDS:
    errors.append(f"  - enrichment/axes.py NOVELS tuple (NOVEL_IDS)")
if novel not in SEGMENT_NOVELS:
    errors.append(f"  - enrichment/segment_novel.py NOVELS dict (gutenberg_id, html_filename)")
if novel not in NOVEL_CONFIGS:
    errors.append(f"  - enrichment/novel_prompts.py NOVEL_CONFIGS + ARCS")
if errors:
    print(f"Novel '{novel}' is not registered in:")
    for e in errors: print(e)
    print()
    print("Add the missing entries before running this script.")
    raise SystemExit(1)
PY

# Pull gutenberg_id + html_filename from the registry.
read -r GUTENBERG_ID HTML_FILENAME <<<"$(
    uv run python -c "
from enrichment.segment_novel import NOVELS
n = NOVELS['${NOVEL}']
print(n.gutenberg_id, n.html_filename)
"
)"

mkdir -p "$NOVEL_DIR"

echo "==> Onboarding novel: $NOVEL  (gutenberg_id=$GUTENBERG_ID)"
echo "    target dir:        $NOVEL_DIR"
echo

# Step 1: Download HTML from Gutenberg.
if [ -f "$NOVEL_DIR/$HTML_FILENAME" ]; then
    echo "==> [1/5] HTML already present at $NOVEL_DIR/$HTML_FILENAME — skipping"
else
    echo "==> [1/5] download HTML from Gutenberg"
    curl -fsSL \
        "https://www.gutenberg.org/cache/epub/${GUTENBERG_ID}/${HTML_FILENAME}" \
        -o "$NOVEL_DIR/$HTML_FILENAME"
fi

# Step 2: Chapter / passage segmentation.
if [ -f "$NOVEL_DIR/passages_raw.json" ]; then
    echo "==> [2/5] passages_raw.json already present — skipping"
else
    echo "==> [2/5] segment chapters into passages"
    uv run python -m enrichment.segment_novel --novel "$NOVEL"
fi

# Step 3: Submit + collect Phase-0 enrichment batch (literary features).
if [ -f "$NOVEL_DIR/passages_enriched.json" ]; then
    echo "==> [3/5] passages_enriched.json already present — skipping enrichment batch"
else
    echo "==> [3/5] submit + collect literary-features batch (polls; up to ~1 hr)"
    uv run python -m enrichment.submit_passages_enriched --novel "$NOVEL"
    uv run python -m enrichment.collect_passages_enriched --novel "$NOVEL"
fi

# Step 4: Submit + poll-collect passage contexts batch.
if [ -f "$NOVEL_DIR/passages_contextual.json" ]; then
    echo "==> [4/5] passages_contextual.json already present — skipping contexts batch"
else
    echo "==> [4/5] submit passage-contexts batch"
    uv run python -m enrichment.submit_passage_contexts --novel "$NOVEL"
    echo "    polling every 60s until the contexts batch ends..."
    while [ ! -f "$NOVEL_DIR/passages_contextual.json" ]; do
        sleep 60
        uv run python -m enrichment.collect_passage_contexts --novel "$NOVEL"
    done
fi

# Step 5: Cluster (literary features + character co-occurrence).
if [ -f "$NOVEL_DIR/clusters_literary.json" ]; then
    echo "==> [5/5] clusters_literary.json already present — skipping"
else
    echo "==> [5/5a] cluster passages by literary features"
    uv run python -m enrichment.cluster_literary --novel "$NOVEL"
fi
if [ -f "$NOVEL_DIR/clusters_characters.json" ]; then
    echo "==> [5/5] clusters_characters.json already present — skipping"
else
    echo "==> [5/5b] cluster passages by character co-occurrence"
    uv run python -m enrichment.cluster_characters --novel "$NOVEL"
fi

echo
echo "SUCCESS: $NOVEL onboarded. Artefacts at $NOVEL_DIR/"
echo "Next: bash scripts/run_one.sh $NOVEL ... (or invoke run_pipeline.py directly)"
