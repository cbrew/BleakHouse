FROM python:3.13-slim

WORKDIR /app

# Install only what the webapp needs
RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Copy webapp code
COPY webapp/ webapp/

# Copy audio data (6 runs: 2 novels × 3 conditions)
COPY data/runs/ext_v01_baseline/audio/ data/runs/ext_v01_baseline/audio/
COPY data/runs/ext_v19_all_swapped/audio/ data/runs/ext_v19_all_swapped/audio/
COPY data/runs/nop_v19_all_swapped/audio/ data/runs/nop_v19_all_swapped/audio/
COPY data/runs/motf_ext_v01_baseline/audio/ data/runs/motf_ext_v01_baseline/audio/
COPY data/runs/motf_ext_v19_all_swapped/audio/ data/runs/motf_ext_v19_all_swapped/audio/
COPY data/runs/motf_nop_v19_all_swapped/audio/ data/runs/motf_nop_v19_all_swapped/audio/

EXPOSE 8080

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
