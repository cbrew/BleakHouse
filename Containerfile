FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] kokoro-onnx soundfile

# Copy webapp code
COPY webapp/ webapp/

# Copy staged demo data (183 runs: 180 tracker grid + 3 interdisciplinary)
# Audio mp3s are served from a fly volume mounted at /app/data/runs/*/audio/
COPY demo_data/ data/

EXPOSE 8080

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
