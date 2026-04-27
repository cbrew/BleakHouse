"""FastAPI app + bearer auth + background worker.

Run: python -m experiments.qwen_tts_server.app
or:  uvicorn experiments.qwen_tts_server.app:make_default_app
"""
# NOTE: deliberately NO `from __future__ import annotations` — pydantic/FastAPI
# need eager evaluation of `Depends(auth)` because `auth` is a closure local to
# build_app(); under PEP 563 string annotations, FastAPI resolves it against
# module globals, doesn't find it, and silently mistakes the parameter for a
# query field, returning a confusing 422.

import hmac
import logging
import shutil
import threading
import traceback
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .state import Config, Job, JobStatus, JobStorage, JobStore, job_hash

logger = logging.getLogger(__name__)


# ---------- Schemas ------------------------------------------------------

class JobView(BaseModel):
    id: str
    hash: str
    run_id: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    job: JobView
    existing: bool


class JobListResponse(BaseModel):
    jobs: list[JobView]


def _job_to_view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        hash=job.hash,
        run_id=job.run_id,
        status=job.status.value,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        progress=job.progress,
    )


# ---------- Bearer auth --------------------------------------------------

def bearer_auth_factory(token_path: Path) -> Callable[[str | None], str]:
    expected = token_path.read_text().strip()
    if not expected:
        raise RuntimeError(f"empty auth token at {token_path}")

    def _dep(authorization: str | None = Header(default=None)) -> str:
        if authorization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing Authorization header",
            )
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="expected Bearer scheme",
            )
        provided = authorization[7:].strip()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid token")
        return provided

    return _dep


# ---------- Worker -------------------------------------------------------

# kwargs: run_dir, refs_dir, out_dir, ref_source, log_file, cancel_check
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
            target=self._loop, name="qwen-tts-worker", daemon=True,
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


# ---------- App factory --------------------------------------------------

def build_app(cfg: Config, *, run_worker: bool = True) -> FastAPI:
    cfg.ensure_dirs()
    store = JobStore(cfg.db_path)
    store.init_schema()
    auth = bearer_auth_factory(cfg.token_path)
    worker = Worker(cfg=cfg, store=store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if run_worker:
            worker.start()
        try:
            yield
        finally:
            if run_worker:
                worker.stop()

    app = FastAPI(title="qwen-tts-server", lifespan=lifespan)

    @app.post("/render", response_model=CreateJobResponse, status_code=201)
    async def render(
        _token: Annotated[str, Depends(auth)],
        manifest: Annotated[UploadFile, File()],
        phase3: Annotated[UploadFile, File()],
        ref_source: Annotated[UploadFile, File()],
        run_id: Annotated[str, Form()],
    ) -> Response:
        manifest_bytes = await manifest.read()
        phase3_bytes = await phase3.read()
        ref_bytes = await ref_source.read()

        # Stage uploads under _staging_<uuid>/, hash them, then either drop
        # the dir (idempotency hit) or rename to <job_id>/ atomically.
        tmp_id = uuid.uuid4().hex
        tmp_storage = JobStorage(cfg.jobs_dir, f"_staging_{tmp_id}")
        tmp_storage.create()
        tmp_storage.save_input("manifest.json", manifest_bytes)
        tmp_storage.save_input("phase3_episode.json", phase3_bytes)
        tmp_storage.save_input("ref_source.mp3", ref_bytes)

        h = job_hash(
            [
                tmp_storage.inputs / "manifest.json",
                tmp_storage.inputs / "phase3_episode.json",
                tmp_storage.inputs / "ref_source.mp3",
            ],
            code_rev=cfg.code_rev(),
        )

        existing = store.get_by_hash(h)
        if existing is not None:
            _rmtree(tmp_storage.root)
            return _json_response(
                CreateJobResponse(job=_job_to_view(existing), existing=True),
                status_code=200,
            )

        job_id = uuid.uuid4().hex
        final = JobStorage(cfg.jobs_dir, job_id)
        tmp_storage.root.rename(final.root)

        job = store.create(job_id=job_id, hash_=h, run_id=run_id)
        worker.notify()
        return _json_response(
            CreateJobResponse(job=_job_to_view(job), existing=False),
            status_code=201,
        )

    @app.get("/jobs", response_model=JobListResponse)
    def list_jobs(_token: Annotated[str, Depends(auth)]) -> JobListResponse:
        return JobListResponse(jobs=[_job_to_view(j) for j in store.list_jobs()])

    @app.get("/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str, _token: Annotated[str, Depends(auth)]) -> JobView:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_to_view(job)

    @app.get("/jobs/{job_id}/result/{name}")
    def get_result(job_id: str, name: str, _token: Annotated[str, Depends(auth)]) -> FileResponse:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != JobStatus.SUCCEEDED:
            raise HTTPException(status_code=409, detail=f"job status is {job.status.value}")
        storage = JobStorage(cfg.jobs_dir, job_id)
        try:
            path = storage.result_path(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid result name") from exc
        if not path.exists():
            raise HTTPException(status_code=404, detail="result file not found")
        return FileResponse(path)

    @app.get("/jobs/{job_id}/log")
    def get_log(job_id: str, _token: Annotated[str, Depends(auth)]) -> Response:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        log_path = JobStorage(cfg.jobs_dir, job_id).log
        if not log_path.exists():
            return Response(content="", media_type="text/plain")
        return Response(content=log_path.read_text(), media_type="text/plain")

    @app.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, _token: Annotated[str, Depends(auth)]) -> Response:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            store.mark_cancelled(job_id)
            worker.cancel(job_id)
        else:
            storage = JobStorage(cfg.jobs_dir, job_id)
            _rmtree(storage.root)
            store.delete(job_id)
        return Response(status_code=204)

    return app


def _json_response(model: CreateJobResponse, *, status_code: int) -> Response:
    return Response(
        content=model.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
    )


def _rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config.from_env()
    app = build_app(cfg, run_worker=True)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port, log_level="info")


if __name__ == "__main__":
    main()
