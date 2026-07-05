"""
Tests for the GET /graph endpoint-level node model (spec v2-11):
- Single joined query (consumer_edges JOIN services JOIN endpoints JOIN services)
- Endpoint node id format: "ep:{endpoint_id}"
- Caller node id format: "caller:{caller_service_id}:{caller_file_path}:{caller_function_name}"
- Endpoint node carries method/path/function_name/file_path/service_name/service_id
- Caller node carries function_name/file_path/service_name/service_id
- Edge source/target reference the node ids above, no endpoint_path/endpoint_method fields
- Nodes/edges are deduplicated by id across multiple consumer_edges rows
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
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
    """Return a mock asyncpg pool whose acquire() yields conn each time."""
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


def _row(**overrides):
    row = {
        "endpoint_id": 9,
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
        "call_count": 3,
        "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return _Row(row)


# ---------------------------------------------------------------------------
# test_graph_endpoint_node_uses_ep_prefix
# ---------------------------------------------------------------------------

async def test_graph_endpoint_node_uses_ep_prefix():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row()])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    node_ids = [n["id"] for n in data["nodes"]]
    assert "ep:9" in node_ids
    assert "9" not in node_ids


# ---------------------------------------------------------------------------
# test_graph_caller_node_uses_caller_prefix_with_file_and_function
# ---------------------------------------------------------------------------

async def test_graph_caller_node_uses_caller_prefix_with_file_and_function():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row()])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    caller_node = next(n for n in data["nodes"] if n["node_type"] == "caller")
    assert caller_node["id"] == "caller:1:lib/api.js:fetchUser"
    assert caller_node["function_name"] == "fetchUser"
    assert caller_node["file_path"] == "lib/api.js"
    assert caller_node["service_name"] == "order-service"
    assert caller_node["service_id"] == 1


# ---------------------------------------------------------------------------
# test_graph_endpoint_node_label_includes_function_name_and_method_path
# ---------------------------------------------------------------------------

async def test_graph_endpoint_node_label_includes_function_name_and_method_path():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row(
        endpoint_id=4, method="POST", path="/orders/create", endpoint_function_name="create_order",
    )])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    endpoint_node = next(n for n in data["nodes"] if n["id"] == "ep:4")
    assert endpoint_node["label"] == "create_order\nPOST /orders/create"
    assert endpoint_node["method"] == "POST"
    assert endpoint_node["path"] == "/orders/create"


async def test_graph_endpoint_node_label_falls_back_without_function_name():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row(
        endpoint_id=4, method="POST", path="/orders/create", endpoint_function_name=None,
    )])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    endpoint_node = next(n for n in data["nodes"] if n["id"] == "ep:4")
    assert endpoint_node["label"] == "POST /orders/create"


# ---------------------------------------------------------------------------
# test_graph_no_nodes_when_no_consumer_edges
# ---------------------------------------------------------------------------

async def test_graph_no_nodes_when_no_consumer_edges():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert resp.status_code == 200
    assert data["nodes"] == []
    assert data["edges"] == []


# ---------------------------------------------------------------------------
# test_graph_edge_target_has_ep_prefix
# ---------------------------------------------------------------------------

async def test_graph_edge_target_has_ep_prefix():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row(endpoint_id=7, path="/items/{id}", method="DELETE")])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["target"] == "ep:7"
    assert data["edges"][0]["target"] != "7"


# ---------------------------------------------------------------------------
# test_graph_edge_source_is_caller_node_id_not_endpoint_owner
# ---------------------------------------------------------------------------

async def test_graph_edge_source_is_caller_node_id_not_endpoint_owner():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_row(
        endpoint_id=5, endpoint_service_id=10, endpoint_service_name="user-service",
        caller_service_id=3, caller_service_name="payment-service",
    )])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    caller_node = next(n for n in data["nodes"] if n["node_type"] == "caller")
    assert data["edges"][0]["source"] == caller_node["id"]
    assert caller_node["service_id"] == 3


# ---------------------------------------------------------------------------
# test_graph_multiple_edges_distinct_endpoints_and_callers
# ---------------------------------------------------------------------------

async def test_graph_multiple_edges_distinct_endpoints_and_callers():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        _row(endpoint_id=10, path="/users/{id}", caller_service_id=1,
             caller_service_name="order-service", caller_file_path="lib/api.js",
             caller_function_name="fetchUser", call_count=5,
             last_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
        _row(endpoint_id=10, path="/users/{id}", caller_service_id=2,
             caller_service_name="payment-service", caller_file_path="lib/client.js",
             caller_function_name="getUser", call_count=3,
             last_seen_at=datetime(2024, 1, 2, tzinfo=timezone.utc)),
        _row(endpoint_id=11, path="/payments/charge", method="POST", caller_service_id=1,
             caller_service_name="order-service", caller_file_path="lib/api.js",
             caller_function_name="fetchUser", call_count=7,
             last_seen_at=datetime(2024, 1, 3, tzinfo=timezone.utc)),
    ])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert resp.status_code == 200
    node_ids = {n["id"] for n in data["nodes"]}
    # Two distinct endpoints + two distinct callers (order-service's fetchUser is reused across rows 1 and 3)
    assert "ep:10" in node_ids
    assert "ep:11" in node_ids
    assert len(data["nodes"]) == 4
    assert len(data["edges"]) == 3


# ---------------------------------------------------------------------------
# test_graph_executes_exactly_one_db_query
# ---------------------------------------------------------------------------

async def test_graph_executes_exactly_one_db_query():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    assert conn.fetch.call_count == 1
