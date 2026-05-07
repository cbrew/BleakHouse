#!/bin/bash
# Deploy the Fly demo. Two steps:
#   1. tar ... — bundle the non-audio data/runs/ tree
#   2. fly deploy --local-only — build via local podman, push image,
#      restart machine. Fly's healthcheck refuses to mark the deploy
#      successful if the new machine doesn't respond.
#
# Audio mp3s stay in R2 (webapp 302-redirects). The tarball excludes
# them so the image stays ~165 MB instead of ~4 GB.
set -euo pipefail
cd "$(dirname "$0")/.."

# Bundles data/runs/ + data/experiments.db (the tracker's matrix
# source). data/runs/<run>/audio/assets.json is the per-run R2-md5
# index the webapp walks at startup; .json is included, mp3s excluded.
tar -chf data-runs.tar \
    --exclude='audio/podcast*.mp3' \
    --exclude='audio/shards/*.mp3' \
    --exclude='data/runs/._runs' \
    data/runs/ \
    data/experiments.db

trap 'rm -f data-runs.tar' EXIT
fly deploy --local-only --yes -a "${FLY_APP:-bleakhouse-demo}"
