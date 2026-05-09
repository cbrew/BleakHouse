FROM python:3.13-slim

WORKDIR /app

# Minimal runtime deps: webapp only. No DVC binary (data is baked in
# at build time via the data-runs.tar tarball below); no git.
RUN pip install --no-cache-dir \
    fastapi \
    'uvicorn[standard]' \
    jinja2 \
    pyyaml \
    pydantic

# /app on PYTHONPATH so `webapp.app:app` and `enrichment.expdb` import
# without an editable install of the project.
ENV PYTHONPATH=/app

# webapp/db.py refreshes experiments.db on first read by re-scanning
# data/runs/ — which destroys the bundled DB in this image. Skip the
# refresh; the bundled DB is the deploy-time snapshot, authoritative
# until the next image rebuild.
ENV BLEAKHOUSE_DB_READONLY=1

# Application code.
COPY webapp/ webapp/
COPY cas/ cas/
COPY enrichment/__init__.py enrichment/__init__.py
COPY enrichment/axes.py enrichment/axes.py
COPY enrichment/params.py enrichment/params.py
COPY enrichment/expdb/ enrichment/expdb/
COPY scripts/generate_runs_yaml.py scripts/generate_runs_yaml.py

# params.yaml is read at import time by enrichment/params.py and
# enrichment/axes.py (generator definitions). runs.yaml is the
# canonical run list. dvc.yaml/dvc.lock retired in BleakHouse-zmlw.
COPY params.yaml runs.yaml ./

# Poster + static assets. (poster/screenshots/ no longer in tree;
# poster_print.html screenshot tags will render as broken images.)
COPY poster/poster_print.html poster/
COPY poster/poster_provenance.js poster/
COPY poster/TheOhioStateUniversity-Scarlet-Vert-RGBHEX.jpg poster/
COPY poster/lexisplusailogo.png poster/

# Bake the dvc-pulled non-audio data/runs/ tree at build time.
# scripts/deploy_demo.sh creates this tarball with `tar -ch` (dereference
# symlinks) before invoking `fly deploy`. Audio mp3s deliberately
# excluded — webapp 302-redirects them to R2.
COPY data-runs.tar /tmp/
RUN tar -xf /tmp/data-runs.tar -C /app && rm /tmp/data-runs.tar

EXPOSE 8080
CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
