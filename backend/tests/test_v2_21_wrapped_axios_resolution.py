"""
Integration coverage for v2-open-issues.md Issue 10 / spec v2-21 — recognizing HTTP
calls made through a wrapped axios instance (`const api = axios.create(...)`), end to
end through the /analyze pipeline (real files on disk, real parsing -- nothing in
analysis.code_parser is mocked here, only clone_repo/delete_repo/the DB connection).

Reproduces the real next-craft/NextPrep repo shape: frontend/lib/api.js creates and
default-exports a shared axios instance, and frontend/lib/queries.js imports it as
`api` and calls `api.get(...)`. Before this fix, _is_axios_call only ever recognized
the literal identifier "axios", so every one of these call sites was silently dropped.
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


def _build_frontend(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "api.js").write_text(
        'import axios from "axios"\n\n'
        "const api = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL })\n\n"
        "export default api\n"
    )
    (lib_dir / "queries.js").write_text(
        'import api from "@/lib/api"\n\n'
        "export async function useMe() {\n"
        '  return (await api.get("/users/me")).data\n'
        "}\n"
    )


async def test_analyze_creates_edge_for_call_through_wrapped_axios_instance(tmp_path):
    _build_frontend(tmp_path)

    caller_service_row = _Row({"id": 1})
    known_endpoint = _Row({"id": 10, "method": "GET", "path": "/users/me", "service_id": 100})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=caller_service_row)
    conn.fetch = AsyncMock(return_value=[known_endpoint])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 1

    edge_calls = [c for c in conn.execute.call_args_list if "consumer_edges" in c.args[0]]
    assert len(edge_calls) == 1
    assert edge_calls[0].args[2] == 10  # matched_endpoint["id"]
    assert edge_calls[0].args[4] == "lib/queries.js"  # caller_rel_path
    assert edge_calls[0].args[5] == "useMe"  # caller_function_name


async def test_analyze_unrelated_dot_get_call_not_treated_as_axios(tmp_path):
    """A same-shaped `.get(...)` call on some unrelated object (not traced back to an
    axios.create() export) must not produce an edge -- the resolution has to be
    precise, not "any identifier.get(...) is an HTTP call"."""
    (tmp_path / "package.json").write_text("{}")
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "cache.js").write_text(
        "const cache = new Map()\n"
        "export default cache\n"
    )
    (lib_dir / "queries.js").write_text(
        'import cache from "@/lib/cache"\n\n'
        'export function readCached() {\n'
        '  return cache.get("/users/me")\n'
        "}\n"
    )

    caller_service_row = _Row({"id": 1})
    known_endpoint = _Row({"id": 10, "method": "GET", "path": "/users/me", "service_id": 100})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=caller_service_row)
    conn.fetch = AsyncMock(return_value=[known_endpoint])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0
