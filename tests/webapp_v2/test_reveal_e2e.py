"""End-to-end Playwright test for turn-level passage reveals.

Spins up real uvicorn against the real content.db, drives Chromium
through the WH literary listen page, and verifies:

  1. clicking a passage handle populates the turn's reveal slot via
     htmx, and the handle gains .passage-handle-open;
  2. clicking the same handle again clears the slot (toggle close);
  3. clicking a *different* turn's handle while one is open closes
     the first and opens the second (single-open semantics);
  4. the audio shards manifest is reachable.

Browser-only behaviours (htmx swaps, the click-toggle JS) can't be
exercised by TestClient; this protects them. ~3-5s including browser
launch. Skipped if playwright browsers aren't installed.
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


def test_handle_opens_and_closes_on_repeat_click(
    live_server: str, browser,
) -> None:
    page = browser.new_page()
    try:
        page.goto(f"{live_server}/listen/wuthering_heights/literary")
        page.wait_for_function(
            "() => typeof window.htmx !== 'undefined'", timeout=10_000,
        )

        handle = page.locator(".passage-handle").first
        handle.wait_for()
        # The handle's own hx-target tells us the slot's id.
        slot_selector = handle.get_attribute("hx-target")
        assert slot_selector and slot_selector.startswith("#reveal-slot-")
        slot = page.locator(slot_selector)

        assert slot.inner_html().strip() == ""
        assert "passage-handle-open" not in (handle.get_attribute("class") or "")

        # First click → fills slot, handle goes open.
        handle.click()
        page.wait_for_selector(f"{slot_selector} .reveal", timeout=5_000)
        assert "reveal-passage-card" in slot.inner_html()
        assert "passage-handle-open" in (handle.get_attribute("class") or "")

        # Second click → clears slot, handle goes resting.
        handle.click()
        page.wait_for_function(
            "() => document.querySelector('.passage-handle.passage-handle-open') === null",
            timeout=2_000,
        )
        assert slot.inner_html().strip() == ""
    finally:
        page.close()


def test_single_open_semantics(live_server: str, browser) -> None:
    """Opening turn B's reveal while turn A's is open must close A."""
    page = browser.new_page()
    try:
        page.goto(f"{live_server}/listen/wuthering_heights/literary")
        page.wait_for_function(
            "() => typeof window.htmx !== 'undefined'", timeout=10_000,
        )

        handles = page.locator(".passage-handle")
        assert handles.count() >= 2, "need >=2 turns with passages"
        a = handles.nth(0)
        b = handles.nth(1)

        a.click()
        page.wait_for_selector(".reveal-slot .reveal", timeout=5_000)
        assert "passage-handle-open" in (a.get_attribute("class") or "")

        b.click()
        # Wait for B's slot to fill AND for A's open class to drop.
        page.wait_for_function(
            """() => {
                const opens = document.querySelectorAll('.passage-handle-open');
                return opens.length === 1;
            }""",
            timeout=5_000,
        )
        a_classes = a.get_attribute("class") or ""
        b_classes = b.get_attribute("class") or ""
        assert "passage-handle-open" not in a_classes
        assert "passage-handle-open" in b_classes

        # Exactly one open reveal in the document.
        revealed = page.locator(".reveal-slot .reveal")
        assert revealed.count() == 1
    finally:
        page.close()


def test_audio_shards_manifest_reachable(live_server: str) -> None:
    import urllib.request
    import json
    with urllib.request.urlopen(
        f"{live_server}/audio/wh_trn_literary_short/shards.json"
    ) as resp:
        data = json.loads(resp.read())
    assert data["shards"]
    assert all(s.get("url", "").startswith("https://") for s in data["shards"])


def test_tab_navigation_switches_pages(live_server: str, browser) -> None:
    """Click each tab in turn; verify the right tab gets aria-current
    and the URL changes accordingly."""
    page = browser.new_page()
    try:
        page.goto(f"{live_server}/listen/wuthering_heights/literary")
        # Script tab is the default landing.
        active = page.locator(".tab[aria-current='page']")
        assert active.text_content() == "Script"

        for label, suffix in (
            ("Expert Interviews", "/interviews"),
            ("Expert Profiles",   "/profiles"),
            ("Character Arcs",    "/arcs"),
            ("Reading List",      "/reading-list"),
            ("Script",            ""),
        ):
            page.locator(f'.tab:has-text("{label}")').first.click()
            page.wait_for_url(
                f"**/listen/wuthering_heights/literary{suffix}",
                timeout=5_000,
            )
            active = page.locator(".tab[aria-current='page']")
            assert active.text_content() == label
    finally:
        page.close()
