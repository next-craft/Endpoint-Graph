"""
Independent tests for GET /graph?repo_id=... (spec v2-08-scoped-graph).

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
# Row fixtures
# ---------------------------------------------------------------------------

_SVC_ORDER = {"id": 1, "name": "order-service"}
_SVC_USER = {"id": 2, "name": "user-service"}
_SVC_PAYMENT = {"id": 3, "name": "payment-service"}

_EP_GET_USER = {"id": 10, "method": "GET", "path": "/users/{id}"}

_EDGE_ORDER_TO_USER = {
    "caller_service_id": 1,
    "endpoint_id": 10,
    "endpoint_path": "/users/{id}",
    "endpoint_method": "GET",
    "call_count": 5,
    "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
}

_EDGE_PAYMENT_TO_USER = {
    "caller_service_id": 3,
    "endpoint_id": 10,
    "endpoint_path": "/users/{id}",
    "endpoint_method": "GET",
    "call_count": 2,
    "last_seen_at": datetime(2024, 2, 1, tzinfo=timezone.utc),
}


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


def _conn_returning(service_rows, endpoint_rows, edge_rows):
    """conn.fetch() is called exactly 3 times in get_graph, in this order:
    services, then endpoints, then edges."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
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

async def test_get_graph_returns_service_and_endpoint_nodes_with_edges():
    conn = _conn_returning(
        service_rows=[_SVC_ORDER, _SVC_USER],
        endpoint_rows=[_EP_GET_USER],
        edge_rows=[_EDGE_ORDER_TO_USER],
    )
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/sample-services")

    assert resp.status_code == 200
    body = resp.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {"1", "2", "endpoint-10"}

    endpoint_node = next(n for n in body["nodes"] if n["id"] == "endpoint-10")
    assert endpoint_node["name"] == "GET /users/{id}"

    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert edge["source"] == "1"
    assert edge["target"] == "endpoint-10"
    assert edge["call_count"] == 5
    assert edge["endpoint_method"] == "GET"
    assert edge["endpoint_path"] == "/users/{id}"


async def test_get_graph_sets_rls_context_with_authenticated_user_before_fetching():
    conn = _conn_returning([], [], [])
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
    conn = _conn_returning([], [], [])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/never-tracked")

    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] == []
    assert body["edges"] == []


async def test_get_graph_services_with_no_consumer_edges_yield_service_nodes_only():
    """A repo can have tracked services with no recorded consumer_edges yet
    (e.g. right after Track, before any caller relationship is discovered).
    No endpoint node should appear because the endpoint query is driven off
    an inner join with consumer_edges."""
    conn = _conn_returning(
        service_rows=[_SVC_ORDER, _SVC_USER],
        endpoint_rows=[],
        edge_rows=[],
    )
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/freshly-tracked")

    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {"1", "2"}
    assert not any(n["id"].startswith("endpoint-") for n in body["nodes"])
    assert body["edges"] == []


async def test_get_graph_repo_id_with_special_characters_forwarded_unchanged():
    """repo_id is used verbatim in every query -- no trimming/decoding should
    be applied by the route itself."""
    tricky_repo_id = "acme-org/sample_services.v2"
    conn = _conn_returning([], [], [])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id=tricky_repo_id)

    assert resp.status_code == 200
    assert conn.fetch.call_count == 3
    for call in conn.fetch.call_args_list:
        assert call.args[-1] == tricky_repo_id


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
    """Exercises the full row-to-graph assembly across 3 services and 2
    edges: the DISTINCT in the endpoint query must collapse the endpoint
    into a single node while both caller edges still surface."""
    conn = _conn_returning(
        service_rows=[_SVC_ORDER, _SVC_USER, _SVC_PAYMENT],
        endpoint_rows=[_EP_GET_USER],
        edge_rows=[_EDGE_ORDER_TO_USER, _EDGE_PAYMENT_TO_USER],
    )
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        resp = await _request(repo_id="acme/sample-services")

    assert resp.status_code == 200
    body = resp.json()

    endpoint_nodes = [n for n in body["nodes"] if n["id"] == "endpoint-10"]
    assert len(endpoint_nodes) == 1

    service_node_ids = {n["id"] for n in body["nodes"] if n["id"] != "endpoint-10"}
    assert service_node_ids == {"1", "2", "3"}

    assert len(body["edges"]) == 2
    sources = {e["source"] for e in body["edges"]}
    assert sources == {"1", "3"}
    assert all(e["target"] == "endpoint-10" for e in body["edges"])
    call_counts = sorted(e["call_count"] for e in body["edges"])
    assert call_counts == [2, 5]
