"""Single-GPU background worker. Runs render jobs sequentially.

The worker owns one Python thread that loops on ``store.pop_next_queued()``.
For each job, it calls ``render_fn`` (default: extract_refs + render_episode
from experiments.qwen_tts.*) and updates the store on success / failure.

``render_fn`` is parameterised so unit tests can inject a stub that doesn't
load the GPU model.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

from .config import Config
from .db import JobStore
from .storage import JobStorage

logger = logging.getLogger(__name__)


# kwargs the worker passes to render_fn:
#   run_dir:      path to the staged inputs/ dir (manifest.json + phase3_episode.json live here)
#   refs_dir:     where extract_refs should write per-speaker WAVs
#   out_dir:      where render_episode should write episode.wav + segment_*.wav + episode.json
#   ref_source:   the uploaded podcast.mp3 used as voice-clone source
#   log_file:     append-mode log path; the renderer should tee its own logs here
#   cancel_check: zero-arg callable returning True if the job has been cancelled
RenderFn = Callable[..., None]


def _default_render(
    *,
    run_dir: Path,
    refs_dir: Path,
    out_dir: Path,
    ref_source: Path,
    log_file: Path,
    cancel_check: Callable[[], bool],
) -> None:
    """Real renderer: extract refs, then render the episode.

    Imports the heavy modules lazily so unit tests don't pay for them.
    """
    from experiments.qwen_tts.extract_refs import extract_refs
    from experiments.qwen_tts.render_episode import render_episode

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a") as lf:
        lf.write("=== extract_refs ===\n")
        lf.flush()
        extract_refs(run_dir=run_dir, out_dir=refs_dir, audio_path=ref_source)
        if cancel_check():
            lf.write("cancelled before render_episode\n")
            return
        lf.write("=== render_episode ===\n")
        lf.flush()
        render_episode(run_dir=run_dir, refs_dir=refs_dir, out_dir=out_dir)


class Worker:
    def __init__(
        self,
        *,
        cfg: Config,
        store: JobStore,
        render_fn: RenderFn | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self._render_fn = render_fn or _default_render
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancelled: set[str] = set()
        self._cancel_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="qwen-tts-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def notify(self) -> None:
        self._wake.set()

    def cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancelled.add(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._cancel_lock:
            return job_id in self._cancelled

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.pop_next_queued()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._run_one(job.id)

    def _run_one(self, job_id: str) -> None:
        storage = JobStorage(self.cfg.jobs_dir, job_id)
        try:
            self._render_fn(
                run_dir=storage.inputs,
                refs_dir=storage.refs,
                out_dir=storage.out,
                ref_source=storage.inputs / "ref_source.mp3",
                log_file=storage.log,
                cancel_check=lambda: self._is_cancelled(job_id),
            )
            if self._is_cancelled(job_id):
                self.store.mark_cancelled(job_id)
            else:
                self.store.mark_succeeded(job_id)
        except Exception as exc:
            tb = traceback.format_exc()
            try:
                with storage.log.open("a") as lf:
                    lf.write(f"\nERROR: {exc}\n{tb}\n")
            except OSError:
                pass
            self.store.mark_failed(job_id, str(exc))
            logger.exception("job %s failed", job_id)
