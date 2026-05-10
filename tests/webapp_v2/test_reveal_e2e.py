"""End-to-end Playwright test for passage reveals.

Spins up real uvicorn against the real content.db, drives Chromium
through the WH literary listen page, and verifies:
  1. clicking a passage-ref button populates the adjacent .reveal-slot
     via htmx,
  2. clicking the same button again clears the slot (toggle helper),
  3. the audio shards manifest is reachable.

Browser-only behaviours (htmx swaps, the click-toggle JS in player.js)
can't be exercised by TestClient; this protects them.

Marked slow; ~3-5s per run including browser launch. Skipped if
playwright browsers aren't installed.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Iterator

import pytest
import uvicorn

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIVE_DB = REPO_ROOT / "data" / "content.db"


pytestmark = pytest.mark.skipif(
    not LIVE_DB.exists(),
    reason="data/content.db not built — run `uv run python scripts/build_content_db.py`",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server() -> Iterator[str]:
    """uvicorn against the real content.db, on a random port, on a
    background thread. Module-scoped so the browser is launched once
    per file."""
    from webapp_v2.app import app

    port = _free_port()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning", lifespan="off", access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not getattr(server, "started", False) and time.time() < deadline:
        time.sleep(0.05)
    if not getattr(server, "started", False):
        raise RuntimeError("uvicorn failed to start within 10s")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium not installed: {e}")
        yield br
        br.close()


def test_reveal_opens_and_closes_on_click(live_server: str, browser) -> None:
    """Click a passage-ref button → htmx fills the adjacent slot.
    Click it again → toggle helper clears it."""
    page = browser.new_page()
    try:
        page.goto(f"{live_server}/listen/wuthering_heights/literary")
        # htmx is loaded with `defer`; wait for it to attach.
        page.wait_for_function("() => typeof window.htmx !== 'undefined'",
                               timeout=10_000)

        ref = page.locator("button.passage-ref").first
        ref.wait_for()
        slot = page.locator("button.passage-ref").first.locator(
            "xpath=../following-sibling::div[contains(@class,'reveal-slot')][1]"
        )

        # Initially empty.
        assert slot.inner_html().strip() == ""

        # First click → htmx fetches and fills.
        ref.click()
        page.wait_for_selector(".reveal-slot .reveal", timeout=5_000)
        first_html = slot.inner_html()
        assert "reveal-passage" in first_html

        # Second click → toggle clears it.
        ref.click()
        page.wait_for_function(
            "() => document.querySelector('.reveal-slot').children.length === 0",
            timeout=2_000,
        )
        assert slot.inner_html().strip() == ""

        # Third click re-opens (proves toggle didn't break the fetch).
        ref.click()
        page.wait_for_selector(".reveal-slot .reveal", timeout=5_000)
        assert "reveal-passage" in slot.inner_html()
    finally:
        page.close()


def test_audio_shards_manifest_reachable(live_server: str) -> None:
    """Sanity: the player's data source returns valid JSON with R2 urls."""
    import urllib.request
    import json
    with urllib.request.urlopen(
        f"{live_server}/audio/wh_trn_literary_short/shards.json"
    ) as resp:
        data = json.loads(resp.read())
    assert data["shards"]
    assert all(s.get("url", "").startswith("https://") for s in data["shards"])
