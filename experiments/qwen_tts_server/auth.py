"""Bearer token dependency factory.

Loads the expected token once at factory time and returns a FastAPI
dependency that compares the incoming bearer in constant time.
"""
from __future__ import annotations

import hmac
from collections.abc import Callable
from pathlib import Path

from fastapi import Header, HTTPException, status


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
