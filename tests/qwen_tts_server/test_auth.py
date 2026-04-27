from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from experiments.qwen_tts_server.app import bearer_auth_factory


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    token_file = tmp_path / "token"
    token_file.write_text("s3cret\n")
    auth = bearer_auth_factory(token_file)
    app = FastAPI()

    @app.get("/ping")
    def _ping(_: str = Depends(auth)) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_missing_header_is_401(app: FastAPI) -> None:
    r = TestClient(app).get("/ping")
    assert r.status_code == 401


def test_wrong_token_is_403(app: FastAPI) -> None:
    r = TestClient(app).get("/ping", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


def test_correct_token_passes(app: FastAPI) -> None:
    r = TestClient(app).get("/ping", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
