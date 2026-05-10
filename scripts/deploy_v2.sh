#!/bin/bash
# Deploy the v2 consumer webapp to a separate Fly app.
#
#   1. Rebuild data/content.db so the image bakes a current snapshot.
#   2. fly deploy --local-only -c fly_v2.toml — builds via local
#      podman/docker, pushes the image, restarts the machine. Fly's
#      healthcheck refuses to mark the deploy successful if the new
#      machine doesn't respond.
#
# Audio mp3s stay in R2 (no secrets in container). The webapp emits
# R2 public URLs from cas.store.url(md5) and the client fetches bytes
# directly.
#
# Target app (configurable via FLY_APP env var) defaults to
# bleakhouse-niot. Runs alongside the v1 demo app — they share
# nothing in flight.
set -euo pipefail
cd "$(dirname "$0")/.."

# Rebuild content.db. Idempotent: same source files produce the same
# bytes, so this is fast if nothing changed since the last build.
echo "==> Rebuilding data/content.db"
uv run python scripts/build_content_db.py

echo "==> Verifying content.db round-trips"
uv run python scripts/build_content_db.py --verify

echo "==> Deploying to Fly app ${FLY_APP:-bleakhouse-niot}"
fly deploy \
    --local-only --yes \
    -c fly_v2.toml \
    -a "${FLY_APP:-bleakhouse-niot}"
