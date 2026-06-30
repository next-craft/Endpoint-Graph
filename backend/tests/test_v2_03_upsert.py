"""
Tests for v2-03-upsert — derived entirely from reading routers/analyze.py.

Covers:
  - repo_id_from_url: edge cases not already in test_routes.py
  - _is_service_folder: all detection scenarios
  - _safe_path: path traversal guard
  - analyze route: upsert SQL content, argument positions, fallback SELECT,
    service name derivation, multiple services, RLS context, spec_source values
"""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from main import app
from routers.analyze import repo_id_from_url, _is_service_folder, _safe_path


HEADERS = {"X-GitHub-Token": "test-token"}
ANALYZE_URL = "/analyze"


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
# repo_id_from_url — edge cases not covered in test_routes.py
# ---------------------------------------------------------------------------

def test_repo_id_from_url_http_scheme():
    """http:// (not only https://) is a valid scheme prefix."""
    assert repo_id_from_url("http://github.com/owner/name") == "owner/name"


def test_repo_id_from_url_trailing_slash():
    """Trailing slash on the URL is stripped before parsing."""
    assert repo_id_from_url("https://github.com/owner/name/") == "owner/name"


def test_repo_id_from_url_leading_and_trailing_whitespace():
    """Leading and trailing whitespace in repo_url is stripped via str.strip()."""
    assert repo_id_from_url("  https://github.com/owner/name  ") == "owner/name"


def test_repo_id_from_url_extra_path_segments_ignored():
    """Extra path segments after owner/name are ignored — only owner/name is returned."""
    assert repo_id_from_url("https://github.com/owner/name/tree/main") == "owner/name"


def test_repo_id_from_url_git_suffix_with_http_scheme():
    """.git suffix is stripped even with http:// scheme."""
    assert repo_id_from_url("http://github.com/owner/name.git") == "owner/name"


def test_repo_id_from_url_only_owner_no_name_raises():
    """URL with only an owner but no repo name (github.com/owner) raises ValueError."""
    with pytest.raises(ValueError):
        repo_id_from_url("github.com/owner")


def test_repo_id_from_url_empty_owner_raises():
    """github.com/ (empty owner segment) raises ValueError — parts[0] is empty."""
    with pytest.raises(ValueError):
        repo_id_from_url("github.com/")


def test_repo_id_from_url_empty_string_raises():
    """Empty string cannot start with 'github.com/' so ValueError is raised."""
    with pytest.raises(ValueError):
        repo_id_from_url("")


def test_repo_id_from_url_returns_exactly_owner_slash_name():
    """Return value is precisely 'owner/name', not any longer path."""
    result = repo_id_from_url("https://github.com/myorg/myrepo")
    assert result == "myorg/myrepo"
    assert result.count("/") == 1


# ---------------------------------------------------------------------------
# _is_service_folder unit tests
# ---------------------------------------------------------------------------

def test_is_service_folder_with_openapi_yaml(tmp_path):
    """Folder containing openapi.yaml is a service folder."""
    (tmp_path / "openapi.yaml").write_text("openapi: '3.0'\n")
    assert _is_service_folder(str(tmp_path)) is True


def test_is_service_folder_with_openapi_json(tmp_path):
    """Folder containing openapi.json is a service folder."""
    (tmp_path / "openapi.json").write_text("{}")
    assert _is_service_folder(str(tmp_path)) is True


def test_is_service_folder_with_python_file(tmp_path):
    """Folder containing a .py file (no openapi spec) is a service folder."""
    (tmp_path / "main.py").write_text("# service")
    assert _is_service_folder(str(tmp_path)) is True


def test_is_service_folder_readme_only_is_false(tmp_path):
    """Folder with only a README.md and no .py or openapi files is NOT a service folder."""
    (tmp_path / "README.md").write_text("# docs only")
    assert _is_service_folder(str(tmp_path)) is False


def test_is_service_folder_empty_is_false(tmp_path):
    """Empty folder is NOT a service folder."""
    assert _is_service_folder(str(tmp_path)) is False


def test_is_service_folder_both_openapi_and_python_is_true(tmp_path):
    """Folder with both openapi.yaml and a .py file is still a service folder."""
    (tmp_path / "openapi.yaml").write_text("openapi: '3.0'\n")
    (tmp_path / "app.py").write_text("# service")
    assert _is_service_folder(str(tmp_path)) is True


def test_is_service_folder_json_extension_only(tmp_path):
    """Folder with only a .json file (not openapi.json by exact name) is NOT a service folder."""
    (tmp_path / "config.json").write_text("{}")
    assert _is_service_folder(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _safe_path unit tests
# ---------------------------------------------------------------------------

def test_safe_path_file_inside_tmp_dir_returns_true(tmp_path):
    """A file nested inside tmp_dir is considered safe."""
    sub = tmp_path / "service"
    sub.mkdir()
    target = sub / "main.py"
    target.write_text("# ok")
    assert _safe_path(str(target), str(tmp_path)) is True


def test_safe_path_file_outside_tmp_dir_returns_false(tmp_path):
    """A file in a sibling directory (outside tmp_dir) is NOT safe."""
    safe_root = tmp_path / "safe_root"
    safe_root.mkdir()
    outside = tmp_path / "outside_root"
    outside.mkdir()
    (outside / "evil.py").write_text("# outside")
    assert _safe_path(str(outside / "evil.py"), str(safe_root)) is False


# ---------------------------------------------------------------------------
# Analyze route — upsert SQL shape assertions
# ---------------------------------------------------------------------------

async def test_analyze_service_upsert_sql_has_on_conflict_do_update(tmp_path):
    """Service INSERT uses ON CONFLICT DO UPDATE, updating last_analyzed_at and language."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    service_sql = conn.fetchrow.call_args_list[0][0][0]
    assert "ON CONFLICT" in service_sql
    assert "DO UPDATE" in service_sql
    assert "last_analyzed_at" in service_sql
    assert "language" in service_sql


async def test_analyze_service_upsert_passes_user_id_as_fourth_arg(tmp_path):
    """user_id from the overridden dependency is the 4th positional arg to service upsert ($4)."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    # (sql, service_name, language, repo_url, user_id, repo_id) — user_id is index 4
    call_args = conn.fetchrow.call_args_list[0][0]
    assert call_args[4] == "test-user-id"  # from conftest autouse override


async def test_analyze_service_upsert_passes_repo_id_as_fifth_arg(tmp_path):
    """repo_id derived from the URL is the 5th positional arg to service upsert ($5)."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL,
                json={"repo_url": "https://github.com/myorg/myrepo"},
                headers=HEADERS,
            )

    assert resp.status_code == 200
    call_args = conn.fetchrow.call_args_list[0][0]
    assert call_args[5] == "myorg/myrepo"  # repo_id derived from URL


async def test_analyze_endpoint_upsert_sql_has_on_conflict_do_nothing(tmp_path):
    """Endpoint INSERT uses ON CONFLICT (service_id, method, path) DO NOTHING."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[_Row({"id": 1}), _Row({"id": 2})])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "GET", "path": "/items", "spec_source": "decorator"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    # Second fetchrow call is the endpoint upsert
    endpoint_sql = conn.fetchrow.call_args_list[1][0][0]
    assert "ON CONFLICT" in endpoint_sql
    assert "DO NOTHING" in endpoint_sql
    # Must NOT use DO UPDATE — endpoint definition is immutable on re-analysis
    assert "DO UPDATE" not in endpoint_sql


async def test_analyze_endpoint_fallback_select_issued_when_upsert_returns_none(tmp_path):
    """When endpoint upsert returns None (DO NOTHING conflict), a fallback SELECT retrieves id."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    # service upsert → row; endpoint upsert → None (conflict); fallback SELECT → existing row
    conn.fetchrow = AsyncMock(side_effect=[
        _Row({"id": 1}),  # service upsert
        None,             # endpoint upsert — DO NOTHING conflict path
        _Row({"id": 7}),  # fallback SELECT
    ])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "GET", "path": "/items", "spec_source": "decorator"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    # Route still reports 1 endpoint even though DO NOTHING was taken
    assert resp.json()["endpoints"] == 1
    # Exactly 3 fetchrow calls: service upsert + endpoint upsert (None) + fallback SELECT
    assert conn.fetchrow.call_count == 3
    fallback_sql = conn.fetchrow.call_args_list[2][0][0]
    assert "SELECT id FROM endpoints" in fallback_sql


async def test_analyze_edge_upsert_sql_has_on_conflict_do_update_last_seen_at(tmp_path):
    """Consumer edge INSERT uses ON CONFLICT DO UPDATE SET last_seen_at, source."""
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

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
               return_value=[{"url": "http://user-service/users/123"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    assert resp.json()["edges"] == 1
    edge_sql_calls = [c[0][0] for c in conn.execute.call_args_list if "consumer_edges" in c[0][0]]
    assert len(edge_sql_calls) == 1
    edge_sql = edge_sql_calls[0]
    assert "ON CONFLICT" in edge_sql
    assert "DO UPDATE" in edge_sql
    assert "last_seen_at" in edge_sql
    assert "source" in edge_sql


async def test_analyze_edge_upsert_source_arg_is_static(tmp_path):
    """Consumer edge upsert always passes source='static' (the 3rd positional arg, $3)."""
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

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
               return_value=[{"url": "http://user-service/users/123"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    edge_calls = [c for c in conn.execute.call_args_list if "consumer_edges" in c[0][0]]
    assert len(edge_calls) == 1
    # execute(sql, caller_service_id, endpoint_id, source) — source is index 3
    source_arg = edge_calls[0][0][3]
    assert source_arg == "static"


# ---------------------------------------------------------------------------
# Analyze route — service name and service count
# ---------------------------------------------------------------------------

async def test_analyze_service_name_is_folder_basename(tmp_path):
    """Service name stored in DB is the basename of the service folder, not its full path."""
    svc_dir = tmp_path / "payment-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    # (sql, service_name, language, repo_url, user_id, repo_id) — service_name is index 1
    service_name_arg = conn.fetchrow.call_args_list[0][0][1]
    assert service_name_arg == "payment-service"


async def test_analyze_multiple_services_counted_correctly(tmp_path):
    """Two service folders in one repo → services count = 2 in the response."""
    for name in ("order-service", "user-service"):
        d = tmp_path / name
        d.mkdir()
        (d / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[_Row({"id": 1}), _Row({"id": 2})])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    assert resp.json()["services"] == 2


# ---------------------------------------------------------------------------
# Analyze route — error path: invalid URL never reaches clone_repo
# ---------------------------------------------------------------------------

async def test_analyze_invalid_url_does_not_call_clone_repo():
    """When repo_id_from_url raises ValueError, clone_repo and delete_repo are never called."""
    with patch("routers.analyze.clone_repo") as mock_clone, \
         patch("routers.analyze.delete_repo") as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL,
                json={"repo_url": "notgithub.com/x/y"},
                headers=HEADERS,
            )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid repo URL"
    mock_clone.assert_not_called()
    mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Analyze route — RLS context is set per transaction with correct user_id
# ---------------------------------------------------------------------------

async def test_analyze_rls_context_claims_contain_correct_user_id(tmp_path):
    """set_rls_context sets request.jwt.claims with the user_id from the JWT sub claim."""
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators", return_value=[]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    # Find the set_config call that carries the JWT claims JSON
    jwt_claims_calls = [
        c for c in conn.execute.call_args_list
        if "request.jwt.claims" in c[0][0]
    ]
    assert len(jwt_claims_calls) > 0, "set_rls_context must issue a set_config for jwt.claims"
    claims = json.loads(jwt_claims_calls[0][0][1])
    # conftest autouse fixture overrides get_current_user_id to return "test-user-id"
    assert claims["sub"] == "test-user-id"


# ---------------------------------------------------------------------------
# Analyze route — spec_source values passed correctly to endpoint upsert
# ---------------------------------------------------------------------------

async def test_analyze_openapi_endpoints_pass_openapi_spec_source(tmp_path):
    """Endpoints from parse_service pass their spec_source (e.g. 'openapi') to the upsert."""
    svc_dir = tmp_path / "user-service"
    svc_dir.mkdir()
    (svc_dir / "openapi.yaml").write_text("openapi: '3.0'\n")
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[_Row({"id": 1}), _Row({"id": 2})])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value={
             "service_name": "user-service",
             "endpoints": [{"method": "GET", "path": "/users/{id}", "spec_source": "openapi"}],
         }), \
         patch("routers.analyze.extract_route_decorators") as mock_dec, \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    assert resp.json()["endpoints"] == 1
    # extract_route_decorators must NOT be called when openapi parse_service succeeds
    mock_dec.assert_not_called()
    # spec_source passed to endpoint upsert: (sql, service_id, method, path, spec_source)
    endpoint_upsert_args = conn.fetchrow.call_args_list[1][0]
    assert endpoint_upsert_args[4] == "openapi"


async def test_analyze_decorator_endpoints_pass_decorator_spec_source(tmp_path):
    """Endpoints from extract_route_decorators pass spec_source='decorator' to the upsert."""
    svc_dir = tmp_path / "user-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[_Row({"id": 1}), _Row({"id": 2})])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "POST", "path": "/users", "spec_source": "decorator"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                ANALYZE_URL, json={"repo_url": "github.com/test/repo"}, headers=HEADERS
            )

    assert resp.status_code == 200
    assert resp.json()["endpoints"] == 1
    # spec_source passed to endpoint upsert: (sql, service_id, method, path, spec_source)
    endpoint_upsert_args = conn.fetchrow.call_args_list[1][0]
    assert endpoint_upsert_args[4] == "decorator"
