import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from main import app
from routers.analyze import _extract_path


HEADERS = {"X-GitHub-Token": "test-token"}
ANALYZE_URL = "/analyze"
PAYLOAD = {"repo_url": "github.com/test/repo"}


class _Row:
    """Minimal asyncpg Record-like object: supports row["key"] and is truthy."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return True


def _make_pool(conn):
    """Return a mock asyncpg pool whose acquire() yields conn each time."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


# ---------------------------------------------------------------------------
# test_analyze_returns_ok_status
# ---------------------------------------------------------------------------

async def test_analyze_returns_ok_status(tmp_path):
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[None, None])  # no existing service, no existing endpoint
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "GET", "path": "/items"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["services"] == 1
    assert data["endpoints"] == 1
    assert data["edges"] == 0


# ---------------------------------------------------------------------------
# test_analyze_invalid_github_url
# ---------------------------------------------------------------------------

async def test_analyze_invalid_github_url():
    with patch("routers.analyze.clone_repo",
               side_effect=ValueError("Invalid GitHub URL: notgithub")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 422
    assert "Invalid repository URL" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_analyze_clone_failure
# ---------------------------------------------------------------------------

async def test_analyze_clone_failure():
    with patch("routers.analyze.clone_repo",
               side_effect=RuntimeError("Clone failed: authentication failed")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 400
    assert "could not be cloned" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_analyze_calls_delete_repo_on_success
# ---------------------------------------------------------------------------

async def test_analyze_calls_delete_repo_on_success(tmp_path):
    # tmp_path is empty — no service folders detected, pipeline runs but finds nothing
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo") as mock_delete, \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    mock_delete.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# test_analyze_calls_delete_repo_on_error
# ---------------------------------------------------------------------------

async def test_analyze_calls_delete_repo_on_error(tmp_path):
    # get_pool raises an unexpected exception after clone_repo succeeds.
    # ASGITransport in tests re-raises unhandled exceptions rather than
    # returning a 500 response, so we catch it with pytest.raises.
    # The finally block still runs before the exception reaches the test.
    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo") as mock_delete, \
         patch("routers.analyze.get_pool",
               new_callable=AsyncMock, side_effect=Exception("DB unavailable")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(Exception, match="DB unavailable"):
                await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    mock_delete.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# test_analyze_uses_openapi_when_present
# ---------------------------------------------------------------------------

async def test_analyze_uses_openapi_when_present(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "openapi.yaml").write_text(
        "openapi: '3.0'\ninfo:\n  title: Order Service\npaths: {}\n"
    )
    (svc_dir / "main.py").write_text("# service code")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service",
               return_value={"service_name": "order-service", "endpoints": []}) as mock_ps, \
         patch("routers.analyze.extract_route_decorators") as mock_dec, \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    mock_ps.assert_called_once()
    mock_dec.assert_not_called()


# ---------------------------------------------------------------------------
# test_analyze_falls_back_to_decorators
# ---------------------------------------------------------------------------

async def test_analyze_falls_back_to_decorators(tmp_path):
    svc_dir = tmp_path / "user-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[None])  # no existing service (no endpoints to insert)
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None) as mock_ps, \
         patch("routers.analyze.extract_route_decorators", return_value=[]) as mock_dec, \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    mock_ps.assert_called_once()
    mock_dec.assert_called()


# ---------------------------------------------------------------------------
# test_analyze_skips_non_service_folders
# ---------------------------------------------------------------------------

async def test_analyze_skips_non_service_folders(tmp_path):
    # Subfolder has only a README — no .py files, no openapi.yaml
    non_svc = tmp_path / "not-a-service"
    non_svc.mkdir()
    (non_svc / "README.md").write_text("# not a service")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["services"] == 0


# ---------------------------------------------------------------------------
# test_analyze_consumer_edge_upserted
# ---------------------------------------------------------------------------

async def test_analyze_consumer_edge_upserted(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    # Service already exists with id=2; endpoint belongs to a different service (id=10)
    svc_row = _Row({"id": 2})
    ep_row = _Row({"id": 5, "method": "GET", "path": "/users/{id}", "service_id": 10})

    conn = AsyncMock()
    # fetchrow called twice: once for service lookup (exists), once for edge pre-check (no existing edge)
    conn.fetchrow = AsyncMock(side_effect=[svc_row, None])
    conn.fetch = AsyncMock(return_value=[ep_row])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls",
               return_value=[{"url": "http://user-service/users/123"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 1


# ---------------------------------------------------------------------------
# test_analyze_skips_fqdn_paths_that_dont_match
# ---------------------------------------------------------------------------

async def test_analyze_skips_fqdn_paths_that_dont_match(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    svc_row = _Row({"id": 2})
    ep_row = _Row({"id": 5, "method": "GET", "path": "/users/{id}", "service_id": 10})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=svc_row)
    conn.fetch = AsyncMock(return_value=[ep_row])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls",
               return_value=[{"url": "http://unknown-service/unknown/path"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0


# ---------------------------------------------------------------------------
# test_analyze_no_self_edges
# ---------------------------------------------------------------------------

async def test_analyze_no_self_edges(tmp_path):
    svc_dir = tmp_path / "item-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    # Endpoint belongs to service_id=2, same as the caller
    svc_row = _Row({"id": 2})
    ep_row = _Row({"id": 3, "method": "GET", "path": "/items/{id}", "service_id": 2})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=svc_row)
    conn.fetch = AsyncMock(return_value=[ep_row])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls",
               return_value=[{"url": "http://item-service/items/1"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0


# ---------------------------------------------------------------------------
# test_extract_path_helper
# ---------------------------------------------------------------------------

def test_extract_path_helper():
    assert _extract_path("http://user-service/users/123") == "/users/123"
    assert _extract_path("http://payment-service/payments/charge") == "/payments/charge"
    assert _extract_path("") is None
    # urlparse("http://svc").path == "" which is falsy → returns None
    assert _extract_path("http://svc") is None
