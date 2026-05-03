#!/bin/bash
# Deploy the Fly demo. Two commands:
#   1. dvc push -r r2 — ensure R2 has the blobs the container will pull
#   2. fly deploy --local-only — build via local podman, push image, restart machine
#
# Fly's healthcheck refuses to mark the deploy successful if the new
# machine doesn't respond, so failure surfaces via fly's own exit code
# and `fly logs`. No local probe / post-deploy curl loop needed.
#
# --local-only because the remote depot builder is unreliable for this
# project (timeouts).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --no-sync dvc push -r r2
fly deploy --local-only --yes -a "${FLY_APP:-bleakhouse-demo}"
