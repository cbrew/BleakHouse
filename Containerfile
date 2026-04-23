FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Copy webapp code
COPY webapp/ webapp/

# webapp.app imports `enrichment.axes` at startup. axes.py is a pure
# stdlib module — no anthropic/openai/hamilton deps — so copy just that
# plus the package __init__; skip the rest of enrichment/ to keep the
# image small and avoid pulling in heavy runtime deps we don't need.
COPY enrichment/__init__.py enrichment/
COPY enrichment/axes.py enrichment/

# Copy poster web assets (HTML + provenance JS + logos + screenshots)
COPY poster/poster_print.html poster/
COPY poster/poster_provenance.js poster/
COPY poster/TheOhioStateUniversity-Scarlet-Vert-RGBHEX.jpg poster/
COPY poster/lexisplusailogo.png poster/
COPY poster/screenshots/ poster/screenshots/

# Copy staged demo data (183 runs: 180 tracker grid + 3 interdisciplinary)
# Audio mp3s are served from a fly volume mounted at /app/data/runs/*/audio/
COPY demo_data/ data/

EXPOSE 8080

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
