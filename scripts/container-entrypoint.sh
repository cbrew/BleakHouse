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

# Materialise data/runs/ from R2. First boot pulls ~600MB; subsequent
# boots use the volume-mounted cache and finish in <1s.
cd /app && uv run --no-sync dvc pull -r r2

# Hand off to the webapp.
exec uv run --no-sync uvicorn webapp.app:app --host 0.0.0.0 --port 8080
