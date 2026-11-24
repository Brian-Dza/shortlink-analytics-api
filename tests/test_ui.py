"""Tests verifying the FastAPI-served web UI and static assets without route regressions."""

import pytest
from httpx import AsyncClient


async def test_root_serves_dashboard_html(client: AsyncClient) -> None:
    """GET / returns 200 HTML containing the dashboard entrypoint and ES module."""
    response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "shortlink-analytics" in response.text
    assert "/static/js/app.js" in response.text


@pytest.mark.parametrize(
    ("asset_path", "expected_prefix"),
    [
        ("/static/css/styles.css", "text/css"),
        ("/static/js/app.js", "javascript"),
        ("/static/js/api.js", "javascript"),
        ("/static/js/charts.js", "javascript"),
        ("/static/js/ui.js", "javascript"),
        ("/static/favicon.svg", "image/svg+xml"),
    ],
)
async def test_static_assets_are_served(
    client: AsyncClient,
    asset_path: str,
    expected_prefix: str,
) -> None:
    """Static UI stylesheets, ES modules, and SVG icon return 200 OK."""
    response = await client.get(asset_path)

    assert response.status_code == 200
    assert expected_prefix in response.headers["content-type"]
    if asset_path.endswith("styles.css"):
        assert "[hidden]" in response.text
        assert "display: none !important" in response.text


async def test_ui_does_not_shadow_redirects_or_docs(client: AsyncClient) -> None:
    """Mounting / and /static keeps /docs and /{short_code} HTTP 307 working."""
    docs_resp = await client.get("/docs")
    assert docs_resp.status_code == 200

    created = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/ui-test", "custom_alias": "uitest1"},
    )
    assert created.status_code == 201

    redirect_resp = await client.get("/uitest1", follow_redirects=False)
    assert redirect_resp.status_code == 307
    assert redirect_resp.headers["Location"] == "https://example.com/ui-test"
