"""Background worker — placeholder; real impl in next task."""
from __future__ import annotations

import logging

from .config import Config
from .db import JobStore

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, *, cfg: Config, store: JobStore) -> None:
        self.cfg = cfg
        self.store = store

    def start(self) -> None:
        logger.info("worker.start (stub)")

    def stop(self) -> None:
        logger.info("worker.stop (stub)")

    def notify(self) -> None:
        pass

    def cancel(self, job_id: str) -> None:
        pass
