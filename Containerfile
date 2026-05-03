FROM python:3.13-slim

WORKDIR /app

# git: required by DVC at runtime (it expects .git/ as a working-tree
# marker; entrypoint runs `git init` to create an empty one). curl is
# handy for in-container debugging.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Minimal runtime deps. The training/eval/notebook dependencies in
# pyproject.toml are deliberately NOT installed here — the container
# only serves the webapp + runs `dvc pull` at startup.
RUN pip install --no-cache-dir \
    fastapi \
    'uvicorn[standard]' \
    jinja2 \
    pyyaml \
    pydantic \
    'dvc>=3.67.1' \
    'dvc-s3>=3.0'

# /app on PYTHONPATH so `webapp.app:app` and `enrichment.expdb` import
# without an editable install of the project.
ENV PYTHONPATH=/app

# Application code.
COPY webapp/ webapp/
COPY enrichment/__init__.py enrichment/__init__.py
COPY enrichment/axes.py enrichment/axes.py
COPY enrichment/params.py enrichment/params.py
COPY enrichment/expdb/ enrichment/expdb/
COPY scripts/generate_runs_yaml.py scripts/generate_runs_yaml.py
COPY scripts/container-entrypoint.sh scripts/container-entrypoint.sh

# Pipeline declarations + runs index. dvc.lock holds the hashes the
# entrypoint's `dvc pull` resolves against; runs.yaml drives foreach.
COPY params.yaml runs.yaml dvc.yaml dvc.lock ./

# Committed DVC config (names R2 remote; secrets injected at runtime via
# .dvc/config.local generated in the entrypoint).
COPY .dvc/config .dvc/config

# Stays-in-git per-run files (tiny). Everything else under data/runs/
# materialises at startup via `dvc pull`.
COPY data/runs/ data/runs/

# Poster + static assets.
COPY poster/poster_print.html poster/
COPY poster/poster_provenance.js poster/
COPY poster/TheOhioStateUniversity-Scarlet-Vert-RGBHEX.jpg poster/
COPY poster/lexisplusailogo.png poster/
COPY poster/screenshots/ poster/screenshots/

EXPOSE 8080
ENTRYPOINT ["scripts/container-entrypoint.sh"]
