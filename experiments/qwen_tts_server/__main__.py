"""Run with: python -m experiments.qwen_tts_server"""
from __future__ import annotations

import logging

import uvicorn

from .config import Config
from .main import build_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config.from_env()
    app = build_app(cfg, run_worker=True)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port, log_level="info")


if __name__ == "__main__":
    main()
