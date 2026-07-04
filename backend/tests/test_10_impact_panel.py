"""
Tests for spec 10 graph endpoint changes:
- 3-query structure (service nodes, endpoint nodes, edge rows)
- Endpoint node id format: "endpoint-{db_id}"
- Endpoint node name format: "METHOD /path"
- Edge target format: "endpoint-{endpoint_id}"
- Edge source: caller_service_id as a string
- No endpoint nodes appear when no consumer_edges rows exist
- Service node ids are plain strings without the "endpoint-" prefix
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


# ---------------------------------------------------------------------------
# test_graph_service_nodes_have_plain_string_id
# Service node ids must be plain strings ("1", "2"), never "endpoint-1".
# ---------------------------------------------------------------------------

async def test_graph_service_nodes_have_plain_string_id():
    service_rows = [_Row({"id": 1, "name": "order-service"})]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, [], []])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    node_ids = [n["id"] for n in data["nodes"]]
    assert "1" in node_ids
    assert "endpoint-1" not in node_ids


# ---------------------------------------------------------------------------
# test_graph_endpoint_nodes_use_endpoint_prefix
# Endpoint node id must be "endpoint-{db_id}", not the bare integer string.
# ---------------------------------------------------------------------------

async def test_graph_endpoint_nodes_use_endpoint_prefix():
    service_rows = [_Row({"id": 2, "name": "user-service"})]
    endpoint_rows = [_Row({"id": 9, "method": "GET", "path": "/users/{id}"})]
    edge_rows = [_Row({
        "caller_service_id": 2,
        "endpoint_id": 9,
        "endpoint_path": "/users/{id}",
        "endpoint_method": "GET",
        "call_count": 3,
        "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    })]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    node_ids = [n["id"] for n in data["nodes"]]
    assert "endpoint-9" in node_ids
    # The bare database id must NOT appear as a standalone node id
    assert "9" not in node_ids


# ---------------------------------------------------------------------------
# test_graph_endpoint_node_name_is_method_space_path
# Endpoint node name must be "METHOD /path" (uppercase method, space, then path).
# ---------------------------------------------------------------------------

async def test_graph_endpoint_node_name_is_method_space_path():
    service_rows = [_Row({"id": 1, "name": "order-service"})]
    endpoint_rows = [_Row({"id": 4, "method": "POST", "path": "/orders/create"})]
    edge_rows = [_Row({
        "caller_service_id": 1,
        "endpoint_id": 4,
        "endpoint_path": "/orders/create",
        "endpoint_method": "POST",
        "call_count": 1,
        "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    })]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    endpoint_node = next(n for n in data["nodes"] if n["id"] == "endpoint-4")
    assert endpoint_node["name"] == "POST /orders/create"


# ---------------------------------------------------------------------------
# test_graph_no_endpoint_nodes_when_no_consumer_edges
# When the endpoint_rows query returns nothing (no consumer_edges JOIN matches),
# only service nodes appear — no "endpoint-*" nodes and no edges.
# ---------------------------------------------------------------------------

async def test_graph_no_endpoint_nodes_when_no_consumer_edges():
    service_rows = [
        _Row({"id": 1, "name": "order-service"}),
        _Row({"id": 2, "name": "user-service"}),
    ]
    conn = AsyncMock()
    # Second fetch (endpoint_rows) and third fetch (edge_rows) both return empty
    conn.fetch = AsyncMock(side_effect=[service_rows, [], []])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert resp.status_code == 200
    # Exactly 2 service nodes, zero endpoint nodes
    assert len(data["nodes"]) == 2
    for node in data["nodes"]:
        assert not node["id"].startswith("endpoint-")
    assert data["edges"] == []


# ---------------------------------------------------------------------------
# test_graph_edge_target_has_endpoint_prefix
# Edge target must point to "endpoint-{endpoint_id}", not a plain service id
# or the bare endpoint database id.
# ---------------------------------------------------------------------------

async def test_graph_edge_target_has_endpoint_prefix():
    service_rows = [_Row({"id": 1, "name": "order-service"})]
    endpoint_rows = [_Row({"id": 7, "method": "DELETE", "path": "/items/{id}"})]
    edge_rows = [_Row({
        "caller_service_id": 1,
        "endpoint_id": 7,
        "endpoint_path": "/items/{id}",
        "endpoint_method": "DELETE",
        "call_count": 2,
        "last_seen_at": datetime(2024, 3, 1, tzinfo=timezone.utc),
    })]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["target"] == "endpoint-7"
    # Must not be the bare endpoint id or the source service id
    assert data["edges"][0]["target"] != "7"
    assert data["edges"][0]["target"] != "1"


# ---------------------------------------------------------------------------
# test_graph_edge_source_is_caller_service_id_string
# Edge source is the CALLER service's id (as a string), not the service that
# owns the endpoint.  caller_service_id=3, endpoint owned by service 10.
# ---------------------------------------------------------------------------

async def test_graph_edge_source_is_caller_service_id_string():
    service_rows = [
        _Row({"id": 3, "name": "payment-service"}),
        _Row({"id": 10, "name": "user-service"}),
    ]
    endpoint_rows = [_Row({"id": 5, "method": "GET", "path": "/users/{id}"})]
    edge_rows = [_Row({
        "caller_service_id": 3,   # payment-service calls user-service's endpoint
        "endpoint_id": 5,
        "endpoint_path": "/users/{id}",
        "endpoint_method": "GET",
        "call_count": 100,
        "last_seen_at": datetime(2024, 2, 1, tzinfo=timezone.utc),
    })]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert data["edges"][0]["source"] == "3"    # caller
    assert data["edges"][0]["source"] != "10"   # owner of the endpoint — must not be source


# ---------------------------------------------------------------------------
# test_graph_multiple_services_and_endpoint_nodes
# 3 service nodes and 2 endpoint nodes coexist; 3 edges present with correct ids.
# ---------------------------------------------------------------------------

async def test_graph_multiple_services_and_endpoint_nodes():
    service_rows = [
        _Row({"id": 1, "name": "order-service"}),
        _Row({"id": 2, "name": "payment-service"}),
        _Row({"id": 3, "name": "user-service"}),
    ]
    endpoint_rows = [
        _Row({"id": 10, "method": "GET", "path": "/users/{id}"}),
        _Row({"id": 11, "method": "POST", "path": "/payments/charge"}),
    ]
    edge_rows = [
        _Row({
            "caller_service_id": 1, "endpoint_id": 10,
            "endpoint_path": "/users/{id}", "endpoint_method": "GET",
            "call_count": 5, "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }),
        _Row({
            "caller_service_id": 2, "endpoint_id": 10,
            "endpoint_path": "/users/{id}", "endpoint_method": "GET",
            "call_count": 3, "last_seen_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        }),
        _Row({
            "caller_service_id": 1, "endpoint_id": 11,
            "endpoint_path": "/payments/charge", "endpoint_method": "POST",
            "call_count": 7, "last_seen_at": datetime(2024, 1, 3, tzinfo=timezone.utc),
        }),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    data = resp.json()
    assert resp.status_code == 200
    # 3 service nodes + 2 endpoint nodes = 5 total
    assert len(data["nodes"]) == 5
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"1", "2", "3", "endpoint-10", "endpoint-11"}
    assert len(data["edges"]) == 3


# ---------------------------------------------------------------------------
# test_graph_executes_exactly_three_db_queries
# The handler must issue exactly 3 conn.fetch calls: one for services,
# one for endpoint nodes (JOIN on consumer_edges), one for edge rows.
# ---------------------------------------------------------------------------

async def test_graph_executes_exactly_three_db_queries():
    service_rows = [_Row({"id": 1, "name": "svc"})]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, [], []])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/graph?repo_id=owner/repo", headers=HEADERS)

    assert conn.fetch.call_count == 3
