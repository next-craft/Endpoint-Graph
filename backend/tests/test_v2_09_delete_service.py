"""
Independent test pass for DELETE /services/{service_id}.

These tests were written from scratch by reading routers/services.py directly
(delete_service handler), NOT from .claude/specs/v2-09-delete-service.md's test
cases, and NOT copied/adapted from the existing DELETE tests in test_routes.py.
Only the generic pytest/httpx/asyncpg-mocking conventions used elsewhere in this
repo were reused (autouse fixtures from conftest.py, AsyncClient + ASGITransport,
mocking conn.transaction() as an async context manager).
"""

from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import AsyncClient, ASGITransport
from main import app


HEADERS = {"X-GitHub-Token": "test-token"}


class _Row:
    """Minimal asyncpg Record-like object: supports row["key"] and is truthy."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return True


def _make_pool(conn):
    """Return a mock asyncpg pool whose acquire() yields conn each time, with
    conn.transaction() usable as an async context manager."""
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


async def _delete(service_id, headers=HEADERS):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.delete(f"/services/{service_id}", headers=headers)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_delete_existing_service_returns_200_and_deleted_status():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 42}))
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(42)

    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}


async def test_delete_executes_delete_query_with_correct_service_id():
    """conn.execute is also used internally by set_rls_context (two
    set_config calls), so assert on the specific DELETE call rather than
    the call count."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 7}))
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(7)

    assert resp.status_code == 200
    delete_calls = [
        c for c in conn.execute.call_args_list
        if c.args and c.args[0] == "DELETE FROM services WHERE id = $1"
    ]
    assert len(delete_calls) == 1
    assert delete_calls[0].args == ("DELETE FROM services WHERE id = $1", 7)


async def test_delete_checks_ownership_with_service_id_and_user_id():
    """The ownership lookup must scope by both the path service_id AND the
    JWT-derived user_id (which the autouse fixture pins to "test-user-id"),
    not just the raw id."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 5}))
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(5)

    assert resp.status_code == 200
    conn.fetchrow.assert_awaited_once_with(
        "SELECT id FROM services WHERE id = $1 AND user_id = $2",
        5,
        "test-user-id",
    )


# ---------------------------------------------------------------------------
# Not found / ownership failure
# ---------------------------------------------------------------------------

async def test_delete_nonexistent_service_returns_404():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(999)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Service not found"


async def test_delete_does_not_execute_delete_when_service_not_found():
    """If the ownership check misses (e.g. service belongs to a different
    user, or doesn't exist), no DELETE statement should ever run. (conn.execute
    is still called internally by set_rls_context, so check specifically for
    the DELETE statement rather than call count.)"""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(999)

    assert resp.status_code == 404
    delete_calls = [
        c for c in conn.execute.call_args_list
        if c.args and c.args[0] == "DELETE FROM services WHERE id = $1"
    ]
    assert delete_calls == []


async def test_delete_service_owned_by_another_user_is_treated_as_not_found():
    """Simulates row-level scoping filtering out a service that exists but
    belongs to a different user: fetchrow correctly returns no row, and the
    route must surface this as a plain 404 (no leak of existence)."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(123)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Service not found"


# ---------------------------------------------------------------------------
# RLS context / transaction ordering
# ---------------------------------------------------------------------------

async def test_delete_sets_rls_context_before_any_query():
    conn = AsyncMock()
    call_order = []

    async def _fake_set_rls_context(c, uid):
        call_order.append(("rls", uid))

    async def _fake_fetchrow(*args, **kwargs):
        call_order.append(("fetchrow", args))
        return _Row({"id": 1})

    async def _fake_execute(*args, **kwargs):
        call_order.append(("execute", args))
        return None

    conn.fetchrow = AsyncMock(side_effect=_fake_fetchrow)
    conn.execute = AsyncMock(side_effect=_fake_execute)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp, \
         patch("routers.services.set_rls_context", new=AsyncMock(side_effect=_fake_set_rls_context)):
        mock_gp.return_value = pool
        resp = await _delete(1)

    assert resp.status_code == 200
    assert [c[0] for c in call_order] == ["rls", "fetchrow", "execute"]
    assert call_order[0] == ("rls", "test-user-id")


# ---------------------------------------------------------------------------
# Path parameter validation
# ---------------------------------------------------------------------------

async def test_delete_service_non_integer_id_returns_422():
    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        resp = await _delete("not-an-int")

    assert resp.status_code == 422
    mock_gp.assert_not_awaited()


async def test_delete_service_negative_id_is_accepted_and_treated_as_not_found():
    """service_id has no ge=0 constraint in the route signature, so a
    negative id is valid input that simply won't match any row."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _delete(-1)

    assert resp.status_code == 404
    conn.fetchrow.assert_awaited_once_with(
        "SELECT id FROM services WHERE id = $1 AND user_id = $2",
        -1,
        "test-user-id",
    )


# ---------------------------------------------------------------------------
# Header / auth failures
# ---------------------------------------------------------------------------

async def test_delete_service_missing_github_token_header_returns_422():
    """X-GitHub-Token has no default, so FastAPI itself rejects the request
    before the route body (or get_pool) ever runs."""
    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        resp = await _delete(1, headers={})

    assert resp.status_code == 422
    mock_gp.assert_not_awaited()


async def test_delete_service_empty_github_token_header_returns_401():
    """An empty (but present) X-GitHub-Token header passes FastAPI's required-
    header check but fails get_github_token's own truthiness check."""
    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        resp = await _delete(1, headers={"X-GitHub-Token": ""})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "GitHub token required"
    mock_gp.assert_not_awaited()


async def test_delete_service_missing_authorization_header_returns_422(real_auth):
    """With the get_current_user_id override popped, Authorization becomes a
    genuinely required header again and FastAPI rejects the request outright."""
    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        resp = await _delete(1, headers=HEADERS)

    assert resp.status_code == 422
    mock_gp.assert_not_awaited()


async def test_delete_service_malformed_authorization_header_returns_401(real_auth):
    """A present-but-non-Bearer Authorization header should be rejected by
    the real get_current_user_id dependency, without ever touching the DB."""
    headers = {**HEADERS, "Authorization": "Basic dXNlcjpwYXNz"}

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        resp = await _delete(1, headers=headers)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing Bearer token"
    mock_gp.assert_not_awaited()
