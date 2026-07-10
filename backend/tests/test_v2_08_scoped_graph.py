"""
Independent tests for GET /graph?repo_id=... (spec v2-08-scoped-graph, updated
for spec v2-11's single-query endpoint/caller node model).

These tests were derived by reading the implemented route
(routers/graph.py), models.py, and auth.py directly -- not from the
spec's own "Test cases" section and not from any other pre-existing
test file for this route.

Auth notes (see backend/tests/conftest.py):
  - `override_get_current_user_id` is autouse and replaces
    get_current_user_id with a fixed "test-user-id" for every test in
    this package, so most tests below don't need to think about JWTs.
  - The `real_auth` fixture temporarily restores the real
    get_current_user_id dependency -- used only for the two tests that
    specifically exercise Authorization-header validation.
  - get_github_token is never overridden globally, so it is exercised
    for real in every test here (a non-empty X-GitHub-Token header is
    always required).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from main import app

GRAPH_URL = "/graph"
HEADERS = {"X-GitHub-Token": "gh-token-abc", "Authorization": "Bearer irrelevant-when-overridden"}

# ---------------------------------------------------------------------------
# Row fixtures — one row per consumer_edges join result (spec v2-11)
# ---------------------------------------------------------------------------

def _row(**overrides):
    row = {
        "endpoint_id": 10,
        "endpoint_service_id": 2,
        "endpoint_service_name": "user-service",
        "endpoint_file_path": "routers/users.py",
        "endpoint_function_name": "get_user",
        "method": "GET",
        "path": "/users/{id}",
        "caller_service_id": 1,
        "caller_service_name": "order-service",
        "caller_file_path": "lib/api.js",
        "caller_function_name": "fetchUser",
        "call_count": 5,
        "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


class _Row:
    """Minimal asyncpg Record-like object: supports row["key"] and is truthy."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return True


_EDGE_ORDER_TO_USER = _Row(_row(
    caller_service_id=1, caller_service_name="order-service",
    caller_file_path="lib/api.js", caller_function_name="fetchUser",
    call_count=5, last_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
))

_EDGE_PAYMENT_TO_USER = _Row(_row(
    caller_service_id=3, caller_service_name="payment-service",
    caller_file_path="lib/client.js", caller_function_name="getUser",
    call_count=2, last_seen_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(conn):
    """Wrap `conn` in a fake asyncpg pool whose acquire()/transaction() are
    async context managers, matching how routers/graph.py uses the pool."""
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


def _conn_returning(rows, service_count=0, endpoint_count=0):
    """conn.fetch() is called exactly once in get_graph (the single joined
    query); conn.fetchrow() is called once for the service_count/endpoint_count
    companion query (v2-open-issues.md issue 8)."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchrow = AsyncMock(
        return_value=_Row({"service_count": service_count, "endpoint_count": endpoint_count})
    )
    conn.execute = AsyncMock()
    return conn


async def _request(repo_id="acme/sample-services", headers=None, params_override=None):
    params = {"repo_id": repo_id} if params_override is None else params_override
    hdrs = HEADERS if headers is None else headers
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(GRAPH_URL, params=params, headers=hdrs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_get_graph_returns_endpoint_and_caller_nodes_with_edges():
    conn = _conn_returning([_EDGE_ORDER_TO_USER], service_count=2, endpoint_count=3)
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/sample-services")

    assert resp.status_code == 200
    body = resp.json()

    endpoint_node = next(n for n in body["nodes"] if n["id"] == "ep:10")
    assert endpoint_node["node_type"] == "endpoint"
    assert endpoint_node["method"] == "GET"
    assert endpoint_node["path"] == "/users/{id}"

    caller_node = next(n for n in body["nodes"] if n["node_type"] == "caller")
    assert caller_node["id"] == "caller:1:lib/api.js:fetchUser"
    assert caller_node["service_name"] == "order-service"

    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert edge["source"] == caller_node["id"]
    assert edge["target"] == "ep:10"
    assert edge["call_count"] == 5

    assert body["service_count"] == 2
    assert body["endpoint_count"] == 3


async def test_get_graph_sets_rls_context_with_authenticated_user_before_fetching():
    conn = _conn_returning([])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/x")

    assert resp.status_code == 200
    # set_rls_context issues exactly two conn.execute calls, both before
    # any conn.fetch call -- verify both content and ordering.
    assert conn.execute.call_count == 2
    claims_call, role_call = conn.execute.call_args_list
    assert claims_call.args[0] == "SELECT set_config('request.jwt.claims', $1, true)"
    assert '"sub": "test-user-id"' in claims_call.args[1]
    assert '"role": "authenticated"' in claims_call.args[1]
    assert role_call.args[0] == "SELECT set_config('role', 'authenticated', true)"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

async def test_get_graph_repo_with_no_tracked_services_returns_empty_graph():
    """service_count/endpoint_count are also 0 here -- this is what lets the
    frontend distinguish "never tracked" from the monolith case below, where
    nodes/edges are equally empty but the repo genuinely was tracked
    (v2-open-issues.md issue 8)."""
    conn = _conn_returning([], service_count=0, endpoint_count=0)
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/never-tracked")

    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["service_count"] == 0
    assert body["endpoint_count"] == 0


async def test_get_graph_services_with_no_consumer_edges_yield_no_nodes():
    """A repo can have tracked services with no recorded consumer_edges yet
    (e.g. right after Track, before any caller relationship is discovered, or
    a single-service monolith that can never have edges -- analyze.py excludes
    self-calls). Per spec v2-11, node identity only exists via consumer_edges
    rows -- a service that neither calls nor is called yields zero nodes, not
    a standalone service-level node (that concept no longer exists). But
    service_count/endpoint_count must still reflect that the repo IS tracked
    (v2-open-issues.md issue 8), unlike the never-tracked case above."""
    conn = _conn_returning([], service_count=1, endpoint_count=6)
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/freshly-tracked")

    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["service_count"] == 1
    assert body["endpoint_count"] == 6


async def test_get_graph_repo_id_with_special_characters_forwarded_unchanged():
    """repo_id is used verbatim in the query -- no trimming/decoding should
    be applied by the route itself."""
    tricky_repo_id = "acme-org/sample_services.v2"
    conn = _conn_returning([])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id=tricky_repo_id)

    assert resp.status_code == 200
    assert conn.fetch.call_count == 1
    assert conn.fetch.call_args.args[-1] == tricky_repo_id
    assert conn.fetchrow.call_args.args[-1] == tricky_repo_id


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

async def test_get_graph_missing_repo_id_query_param_returns_422():
    resp = await _request(params_override={})
    assert resp.status_code == 422


async def test_get_graph_missing_github_token_header_returns_422():
    resp = await _request(headers={"Authorization": "Bearer whatever"})
    assert resp.status_code == 422


async def test_get_graph_empty_github_token_header_returns_401():
    resp = await _request(headers={"X-GitHub-Token": "", "Authorization": "Bearer whatever"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "GitHub token required"


async def test_get_graph_missing_authorization_header_returns_422(real_auth):
    resp = await _request(headers={"X-GitHub-Token": "gh-token-abc"})
    assert resp.status_code == 422


async def test_get_graph_malformed_authorization_header_returns_401(real_auth):
    resp = await _request(
        headers={"X-GitHub-Token": "gh-token-abc", "Authorization": "Token not-a-bearer-value"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing Bearer token"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

async def test_get_graph_endpoint_with_multiple_callers_appears_once_with_two_edges():
    """Exercises the full row-to-graph assembly across 2 caller services and 1
    endpoint: dedup-by-id must collapse the endpoint into a single node while
    both caller edges still surface as two distinct caller nodes/edges."""
    conn = _conn_returning([_EDGE_ORDER_TO_USER, _EDGE_PAYMENT_TO_USER])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/sample-services")

    assert resp.status_code == 200
    body = resp.json()

    endpoint_nodes = [n for n in body["nodes"] if n["id"] == "ep:10"]
    assert len(endpoint_nodes) == 1

    caller_nodes = [n for n in body["nodes"] if n["node_type"] == "caller"]
    assert len(caller_nodes) == 2

    assert len(body["edges"]) == 2
    assert all(e["target"] == "ep:10" for e in body["edges"])
    call_counts = sorted(e["call_count"] for e in body["edges"])
    assert call_counts == [2, 5]
