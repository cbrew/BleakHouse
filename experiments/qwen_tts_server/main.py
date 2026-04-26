"""FastAPI app: POST /render, GET /jobs, GET /jobs/{id}, GET result, DELETE."""
# Note: NO `from __future__ import annotations` here. FastAPI/pydantic need to
# resolve `Depends(auth)` etc. at definition time, but `auth` is captured as a
# closure inside build_app() — under PEP 563 string annotations they're
# resolved against the module globals where `auth` doesn't exist, and you get
# a confusing 422 with `loc=["query","_token"]`.

import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from .auth import bearer_auth_factory
from .config import Config
from .db import Job, JobStatus, JobStore
from .hashing import job_hash
from .schemas import CreateJobResponse, JobListResponse, JobView
from .storage import JobStorage
from .worker import Worker

logger = logging.getLogger(__name__)


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

        # Stage uploads under a `_staging_<uuid>/` dir so we can hash them on
        # disk, then either drop the staging dir (idempotency hit) or rename
        # it to the real <job_id>/ in one move.
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
