FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] jinja2 pyyaml

# Copy webapp code
COPY webapp/ webapp/

# webapp.app imports `enrichment.axes` at startup, which now loads
# DVC-tracked values from params.yaml via enrichment.params. Ship the
# three files it needs plus params.yaml; everything else in enrichment/
# stays out to keep the image small.
COPY enrichment/__init__.py enrichment/
COPY enrichment/axes.py enrichment/
COPY enrichment/params.py enrichment/
COPY params.yaml ./

# Copy poster web assets (HTML + provenance JS + logos + screenshots)
COPY poster/poster_print.html poster/
COPY poster/poster_provenance.js poster/
COPY poster/TheOhioStateUniversity-Scarlet-Vert-RGBHEX.jpg poster/
COPY poster/lexisplusailogo.png poster/
COPY poster/screenshots/ poster/screenshots/

# Copy staged demo data — JSON + report HTML + experiments.db. No mp3s
# in the image any more: audio mp3s live in Cloudflare R2 and the webapp
# 302-redirects /audio/<id>/<file> to https://pub-<hash>.r2.dev/...
# stage_demo.sh strips audio/ subdirs before this COPY runs.
COPY demo_data/ data/

# The bundled experiments.db is read-only; skip the dev-mode mtime check
# in webapp/db.py (which would import enrichment.expdb — not shipped).
ENV BLEAKHOUSE_DB_READONLY=1

EXPOSE 8080

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
