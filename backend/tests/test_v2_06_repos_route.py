import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient as HttpxClient, ASGITransport
import httpx

from main import app


HEADERS = {"X-GitHub-Token": "test-token"}
REPOS_URL = "/repos"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Row:
    """Minimal asyncpg Record-like object."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


def _make_pool(conn):
    """Return a mock asyncpg pool whose acquire() yields conn."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire

    @asynccontextmanager
    async def _transaction():
        yield

    conn.transaction = _transaction
    return pool


def _mock_github(response_data=None, status=200, raise_exc=None):
    """
    Return a patch context for routers.repos.httpx.AsyncClient.
    If raise_exc is set, the get() call raises that exception.
    Otherwise returns a mock response with the given status and data.
    """
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.is_success = (200 <= status < 300)
    mock_response.json.return_value = response_data if response_data is not None else []

    mock_http_client = AsyncMock()
    if raise_exc is not None:
        mock_http_client.get = AsyncMock(side_effect=raise_exc)
    else:
        mock_http_client.get = AsyncMock(return_value=mock_response)

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=None)

    return patch("routers.repos.httpx.AsyncClient", mock_class)


_GITHUB_REPO_1 = {
    "name": "order-service",
    "full_name": "testuser/order-service",
    "private": False,
    "updated_at": "2024-01-01T00:00:00Z",
}

_GITHUB_REPO_2 = {
    "name": "user-service",
    "full_name": "testuser/user-service",
    "private": True,
    "updated_at": "2024-02-01T00:00:00Z",
}

_LAST_ANALYZED = datetime(2024, 3, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# test_get_repos_returns_list
# ---------------------------------------------------------------------------

async def test_get_repos_returns_list():
    """Two GitHub repos; first is tracked in DB, second is not."""
    db_rows = [
        _Row({
            "id": 42,
            "repo_id": "testuser/order-service",
            "last_analyzed_at": _LAST_ANALYZED,
        })
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=db_rows)
    pool = _make_pool(conn)

    with _mock_github([_GITHUB_REPO_1, _GITHUB_REPO_2]), \
         patch("routers.repos.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    first = data[0]
    assert first["full_name"] == "testuser/order-service"
    assert first["tracked"] is True
    assert first["service_id"] == 42
    assert first["last_analyzed_at"] is not None

    second = data[1]
    assert second["full_name"] == "testuser/user-service"
    assert second["tracked"] is False
    assert second["service_id"] is None
    assert second["last_analyzed_at"] is None


# ---------------------------------------------------------------------------
# test_get_repos_all_untracked
# ---------------------------------------------------------------------------

async def test_get_repos_all_untracked():
    """GitHub returns repos but none are tracked in DB."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with _mock_github([_GITHUB_REPO_1, _GITHUB_REPO_2]), \
         patch("routers.repos.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert item["tracked"] is False
        assert item["service_id"] is None
        assert item["last_analyzed_at"] is None


# ---------------------------------------------------------------------------
# test_get_repos_all_tracked
# ---------------------------------------------------------------------------

async def test_get_repos_all_tracked():
    """Both GitHub repos are tracked in DB."""
    db_rows = [
        _Row({"id": 1, "repo_id": "testuser/order-service", "last_analyzed_at": _LAST_ANALYZED}),
        _Row({"id": 2, "repo_id": "testuser/user-service", "last_analyzed_at": _LAST_ANALYZED}),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=db_rows)
    pool = _make_pool(conn)

    with _mock_github([_GITHUB_REPO_1, _GITHUB_REPO_2]), \
         patch("routers.repos.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert item["tracked"] is True
        assert item["service_id"] is not None
        assert item["last_analyzed_at"] is not None


# ---------------------------------------------------------------------------
# test_get_repos_github_401
# ---------------------------------------------------------------------------

async def test_get_repos_github_401():
    """GitHub returns 401 → route raises HTTP 401."""
    with _mock_github(status=401):
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid GitHub token"


# ---------------------------------------------------------------------------
# test_get_repos_github_403
# ---------------------------------------------------------------------------

async def test_get_repos_github_403():
    """GitHub returns 403 → route raises HTTP 401 (same mapping)."""
    with _mock_github(status=403):
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid GitHub token"


# ---------------------------------------------------------------------------
# test_get_repos_github_502
# ---------------------------------------------------------------------------

async def test_get_repos_github_502():
    """GitHub returns 500 → route raises HTTP 502."""
    with _mock_github(status=500):
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 502
    assert resp.json()["detail"] == "GitHub API error"


# ---------------------------------------------------------------------------
# test_get_repos_github_connection_error
# ---------------------------------------------------------------------------

async def test_get_repos_github_connection_error():
    """httpx raises ConnectError (subclass of RequestError) → route raises HTTP 502."""
    with _mock_github(raise_exc=httpx.ConnectError("connection refused")):
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 502
    assert resp.json()["detail"] == "GitHub API unreachable"


# ---------------------------------------------------------------------------
# test_get_repos_empty_github_response
# ---------------------------------------------------------------------------

async def test_get_repos_empty_github_response():
    """GitHub returns empty list → route returns [] without touching the DB."""
    with _mock_github([]), \
         patch("routers.repos.get_pool", new_callable=AsyncMock) as mock_gp:
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(REPOS_URL, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == []
    mock_gp.assert_not_called()


# ---------------------------------------------------------------------------
# test_get_repos_missing_github_token
# ---------------------------------------------------------------------------

async def test_get_repos_missing_github_token():
    """Missing X-GitHub-Token → FastAPI returns 422."""
    async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(REPOS_URL, headers={"Authorization": "Bearer test-jwt"})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# test_get_repos_missing_auth_header
# ---------------------------------------------------------------------------

async def test_get_repos_missing_auth_header(real_auth):
    """Missing Authorization header → FastAPI returns 422 (real auth dependency active)."""
    async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(REPOS_URL, headers={"X-GitHub-Token": "test-token"})

    assert resp.status_code == 422
