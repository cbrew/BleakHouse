#!/bin/bash
# Deploy the Fly demo. Two steps:
#   1. tar -ch ... — bundle the non-audio data/runs/ tree (dereferences
#      DVC symlinks into regular files for the build context)
#   2. fly deploy --local-only — build via local podman, push image,
#      restart machine. Fly's healthcheck refuses to mark the deploy
#      successful if the new machine doesn't respond.
#
# Audio mp3s stay in R2 (webapp 302-redirects). The tarball excludes
# them so the image stays ~165 MB instead of ~4 GB.
#
# Prerequisite: the local DVC cache must be populated. Run
# `uv run dvc pull -r r2` once after clone (documented in CLAUDE.md).
# We deliberately do NOT run dvc pull here: dvc pull treats files
# from removed stages as orphans and deletes git-tracked
# run_manifest.json files from the working tree (BleakHouse-1dnv
# Phase 3 removed the stage but the files stay in git).
set -euo pipefail
cd "$(dirname "$0")/.."

# tar -h dereferences symlinks; without it the build context would carry
# Mac-local /Volumes/Crucial X9/... paths which don't exist in the image.
tar -chf data-runs.tar \
    --exclude='audio/podcast*.mp3' \
    --exclude='audio/shards/*.mp3' \
    data/runs/

trap 'rm -f data-runs.tar' EXIT
fly deploy --local-only --yes -a "${FLY_APP:-bleakhouse-demo}"
