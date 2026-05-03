#!/bin/sh
set -eu

# Generate .dvc/config.local from Fly secrets. The committed .dvc/config
# names the R2 remote; credentials and the runtime cache.dir live here.
mkdir -p /app/.dvc
cat > /app/.dvc/config.local <<CONFIG
[cache]
    dir = /cache
    type = "symlink,hardlink,copy"
['remote "r2"']
    access_key_id = ${DVC_REMOTE_R2_ACCESS_KEY}
    secret_access_key = ${DVC_REMOTE_R2_SECRET_ACCESS_KEY}
CONFIG

# DVC needs a git repo to operate (it uses .git as a marker for the
# working-tree root). The container doesn't ship .git/ — too big and
# we don't need git history at runtime — so create an empty one.
cd /app && git init -q 2>/dev/null || true

# Materialise non-audio data/runs/ from R2. Audio mp3s stay in R2 and
# are 302-redirected by the webapp at request time (~165 MB pull, ~3 s
# cold-start; subsequent boots are no-ops).
#
# Stage list is enumerated explicitly so adding/removing pipeline
# stages doesn't silently change what the container pulls. Audio
# stages (phase4_audio*) deliberately omitted.
cd /app && python -m dvc pull -r r2 \
    phase0_segments \
    phase1_assignments \
    phase1_2_embedding \
    phase2_plan \
    phase2_5 \
    phase2_5_briefs_only \
    phase2_5_reading_list \
    phase2_5_timings \
    phase3_episode \
    phase3_teaser \
    phase4_post \
    phase_timings \
    quote_verification \
    experiments_db

# Hand off to the webapp.
exec uvicorn webapp.app:app --host 0.0.0.0 --port 8080
