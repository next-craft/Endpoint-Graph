"""
Integration coverage for v2-open-issues.md Issue 9 / spec v2-20 — resolving the real
mount path of a FastAPI route through APIRouter(prefix=...) + include_router(prefix=...),
end to end through the /analyze pipeline (real files on disk, real parsing -- nothing
in analysis.code_parser is mocked here, only clone_repo/delete_repo/the DB connection).

Reproduces the real next-craft/NextPrep repo shape: a router file declaring
`router = APIRouter(prefix="/colleges")` with two `@router.get(...)` decorators, mounted
from main.py via `app.include_router(colleges.router, prefix="/v1")`. Before this fix,
the stored path was just the decorator's own literal ("/{slug}"), which both discarded
real prefixes and collapsed onto the same overly generic regex as every other truncated
endpoint in the repo.
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


async def test_analyze_composes_include_router_and_apirouter_prefixes(tmp_path):
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from routers import colleges\n\n"
        "app = FastAPI()\n"
        'app.include_router(colleges.router, prefix="/v1")\n'
    )
    routers_dir = tmp_path / "routers"
    routers_dir.mkdir()
    (routers_dir / "colleges.py").write_text(
        "from fastapi import APIRouter\n\n"
        'router = APIRouter(prefix="/colleges", tags=["colleges"])\n\n'
        '@router.get("", response_model=list)\n'
        "async def list_colleges(): ...\n\n"
        '@router.get("/{slug}")\n'
        "async def get_college(slug: str): ...\n"
    )

    service_row = _Row({"id": 1})
    endpoint_rows = [_Row({"id": 10}), _Row({"id": 11})]

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[service_row, *endpoint_rows])
    conn.fetch = AsyncMock(return_value=[])
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
    assert resp.json()["endpoints"] == 2

    # fetchrow[0] is the service upsert; [1] and [2] are the two endpoint upserts, in
    # the order the decorators appear in colleges.py.
    list_call_args = conn.fetchrow.call_args_list[1][0]
    detail_call_args = conn.fetchrow.call_args_list[2][0]

    # fetchrow(sql, service_id, method, path, spec_source, file_path, function_name)
    assert list_call_args[3] == "/v1/colleges"
    assert list_call_args[6] == "list_colleges"
    assert detail_call_args[3] == "/v1/colleges/{slug}"
    assert detail_call_args[6] == "get_college"


async def test_analyze_router_with_no_local_prefix_still_gets_mount_prefix(tmp_path):
    """chat.py-style router: no APIRouter(prefix=...) of its own, only the
    include_router mount prefix should apply."""
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from routers import chat\n\n"
        "app = FastAPI()\n"
        'app.include_router(chat.router, prefix="/v1")\n'
    )
    routers_dir = tmp_path / "routers"
    routers_dir.mkdir()
    (routers_dir / "chat.py").write_text(
        "from fastapi import APIRouter\n\n"
        'router = APIRouter(tags=["conversations"])\n\n'
        '@router.get("/conversations")\n'
        "async def list_conversations(): ...\n"
    )

    service_row = _Row({"id": 1})
    endpoint_row = _Row({"id": 20})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[service_row, endpoint_row])
    conn.fetch = AsyncMock(return_value=[])
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
    endpoint_call_args = conn.fetchrow.call_args_list[1][0]
    assert endpoint_call_args[3] == "/v1/conversations"


async def test_analyze_no_router_prefix_machinery_leaves_path_unchanged(tmp_path):
    """A plain @app.get(...) with no APIRouter/include_router anywhere must be stored
    exactly as written -- the new resolution must no-op when there's nothing to resolve."""
    (tmp_path / "main.py").write_text(
        '@app.get("/items")\n'
        "async def list_items(): ...\n"
    )

    service_row = _Row({"id": 1})
    endpoint_row = _Row({"id": 30})

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[service_row, endpoint_row])
    conn.fetch = AsyncMock(return_value=[])
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
    endpoint_call_args = conn.fetchrow.call_args_list[1][0]
    assert endpoint_call_args[3] == "/items"
