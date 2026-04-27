"""FastAPI service that owns the pop-os GPU and runs Qwen3-TTS renders.

Three-file standalone package:
    state.py    Config, JobStore, JobStorage, job_hash
    app.py      FastAPI app + bearer auth + Worker
    __init__.py this file

Run with:
    python -m experiments.qwen_tts_server.app

Env (optional):
    QWEN_TTS_STATE_DIR   default /var/lib/qwen-tts-server
    QWEN_TTS_TOKEN_PATH  default /etc/qwen-tts-server/token
    QWEN_TTS_HOST        default 0.0.0.0
    QWEN_TTS_PORT        default 8765
    QWEN_TTS_CODE_REV    optional file containing the renderer git rev
"""
