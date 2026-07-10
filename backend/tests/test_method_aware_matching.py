"""
Regression tests for method-aware call-to-endpoint matching in routers/analyze.py.

Bug: matching was done on URL path alone. When several endpoints share the same
path template but differ by HTTP method (e.g. GET /{id}, PATCH /{id}, DELETE /{id} —
the exact shape of a REST "todo" resource), every caller hitting that path resolved
to whichever endpoint happened to come first in the unordered `known_endpoints`
list, and consumer_edges' UNIQUE(caller_service_id, endpoint_id) constraint then
collapsed all of those distinct calls into a single upserted row.
"""
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from main import app

HEADERS = {"X-GitHub-Token": "test-token"}
ANALYZE_URL = "/analyze"
PAYLOAD = {"repo_url": "github.com/test/repo"}


class _Row:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return True


def _make_pool(conn):
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


async def test_calls_to_shared_path_route_to_distinct_endpoints_by_method(tmp_path):
    """GET/PATCH/DELETE /{id} are three separate endpoints; three distinct calls
    to that same path (one per method) must produce three separate edges, not
    one edge that keeps getting overwritten."""
    caller_dir = tmp_path / "frontend"
    caller_dir.mkdir()
    (caller_dir / "package.json").write_text("{}")
    (caller_dir / "api.js").write_text("// caller code")

    caller_svc_row = _Row({"id": 1})
    endpoints = [
        _Row({"id": 10, "method": "GET", "path": "/{id}", "service_id": 100}),
        _Row({"id": 11, "method": "PATCH", "path": "/{id}", "service_id": 100}),
        _Row({"id": 12, "method": "DELETE", "path": "/{id}", "service_id": 100}),
    ]

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=caller_svc_row)
    conn.fetch = AsyncMock(return_value=endpoints)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    calls = [
        {"url": "http://backend/1", "method": "GET", "file_path": str(caller_dir / "api.js"), "caller_function_name": "getTaskApi"},
        {"url": "http://backend/1", "method": "PATCH", "file_path": str(caller_dir / "api.js"), "caller_function_name": "updateTaskApi"},
        {"url": "http://backend/1", "method": "DELETE", "file_path": str(caller_dir / "api.js"), "caller_function_name": "deleteTaskApi"},
    ]

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_js_routes", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.extract_js_http_calls", return_value=calls), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 3

    edge_calls = [c for c in conn.execute.call_args_list if "consumer_edges" in c.args[0]]
    assert len(edge_calls) == 3
    matched_endpoint_ids = {c.args[2] for c in edge_calls}
    assert matched_endpoint_ids == {10, 11, 12}
    caller_function_names = {c.args[-1] for c in edge_calls}
    assert caller_function_names == {"getTaskApi", "updateTaskApi", "deleteTaskApi"}


async def test_call_with_no_method_key_does_not_match_any_endpoint(tmp_path):
    """A call with no method info (e.g. an older mocked/mis-parsed call) must not
    fall back to matching on path alone — it should simply produce no edge."""
    caller_dir = tmp_path / "frontend"
    caller_dir.mkdir()
    (caller_dir / "package.json").write_text("{}")
    (caller_dir / "api.js").write_text("// caller code")

    caller_svc_row = _Row({"id": 1})
    endpoints = [_Row({"id": 10, "method": "GET", "path": "/{id}", "service_id": 100})]

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=caller_svc_row)
    conn.fetch = AsyncMock(return_value=endpoints)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    calls = [{"url": "http://backend/1", "file_path": str(caller_dir / "api.js"), "caller_function_name": "getTaskApi"}]

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_js_routes", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.extract_js_http_calls", return_value=calls), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0
