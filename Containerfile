FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY enrichment/ enrichment/
COPY webapp/ webapp/

# Install dependencies (no dev deps)
RUN uv sync --no-dev --frozen

# Copy audio data (runs with audio + manifests)
COPY data/runs/ext_v01_baseline/audio/ data/runs/ext_v01_baseline/audio/
COPY data/runs/ext_v01_baseline/phase3_episode.json data/runs/ext_v01_baseline/
COPY data/runs/ext_v19_all_swapped/audio/ data/runs/ext_v19_all_swapped/audio/
COPY data/runs/ext_v19_all_swapped/phase3_episode.json data/runs/ext_v19_all_swapped/

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
