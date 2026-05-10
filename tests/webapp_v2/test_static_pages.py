"""Phase F: smoke tests for the ported static and blog pages."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app

STATIC_ROUTES = ["/about", "/help", "/references", "/research", "/prompts"]
BLOG_POSTS = [
    "audio", "claudecode", "enrichment", "friends", "hostprep",
    "pastiche", "references", "transparency", "transport",
]


@pytest.fixture
def client(fixture_db: Path) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("route", STATIC_ROUTES)
def test_static_routes_return_200(client: TestClient, route: str) -> None:
    r = client.get(route)
    assert r.status_code == 200
    # Site nav + footer rendered (proves base.html applied).
    assert 'class="site-nav"' in r.text
    assert 'class="site-footer"' in r.text


def test_blog_index_returns_200(client: TestClient) -> None:
    r = client.get("/blog")
    assert r.status_code == 200
    assert 'class="site-nav"' in r.text


@pytest.mark.parametrize("post", BLOG_POSTS)
def test_blog_post_returns_200(client: TestClient, post: str) -> None:
    r = client.get(f"/blog/{post}")
    assert r.status_code == 200
    assert 'class="site-nav"' in r.text


def test_blog_post_404_for_unknown_post(client: TestClient) -> None:
    r = client.get("/blog/nonesuch_post")
    assert r.status_code == 404


def test_blog_post_rejects_path_traversal(client: TestClient) -> None:
    """No ../ or / allowed in post_id; safe filenames that happen to
    contain '..' (e.g. 'x..y') are rejected too — the check is on '..'
    substring, which is conservative but safe."""
    assert client.get("/blog/..%2Fbase").status_code in (400, 404)
    # 'x..y' contains '..' so the 400 branch fires — that's intentional
    # over-rejection.
    assert client.get("/blog/x..y").status_code == 400


def test_landing_links_to_static_pages(client: TestClient) -> None:
    """Landing has nav-bar and footer links to the static pages so users
    can actually reach them."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert 'href="/about"' in body
    assert 'href="/blog"' in body
    # Footer link block
    assert 'href="/research"' in body
    assert 'href="/help"' in body


def test_static_images_served_from_v2(client: TestClient) -> None:
    """The about/research pages reference /static/img/*.png; the files
    were copied to webapp_v2/static/img/ during the port."""
    r = client.get("/static/img/pipeline_overview.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_no_dead_v1_links_in_about(client: TestClient) -> None:
    """about.html had /tracker and /script-versions links — both
    v1-only routes. Phase F edited them out."""
    r = client.get("/about")
    body = r.text
    assert 'href="/tracker"' not in body
    assert 'href="/script-versions"' not in body
