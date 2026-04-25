FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] pyyaml

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

# Copy staged demo data (192 runs from the matrix + interdisciplinary +
# alt-generator + versioned). Now includes 31 dereferenced MP3s
# (~3 GB) — stage_demo.sh follows symlinks into the DVC cache so the
# build context has real files.
COPY demo_data/ data/

EXPOSE 8080

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
