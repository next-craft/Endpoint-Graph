import pytest
import jwt
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from main import app
from routers.analyze import _extract_path, repo_id_from_url


HEADERS = {"X-GitHub-Token": "test-token"}
ANALYZE_URL = "/analyze"
PAYLOAD = {"repo_url": "github.com/test/repo"}


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

    # conn.transaction() must work as an async context manager so set_rls_context
    # can be called at the start of every DB transaction.
    @asynccontextmanager
    async def _transaction():
        yield

    conn.transaction = _transaction
    return pool


# ---------------------------------------------------------------------------
# test_analyze_returns_ok_status
# ---------------------------------------------------------------------------

async def test_analyze_returns_ok_status(tmp_path):
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    # service upsert returns the row id; endpoint upsert returns the row id (new row)
    conn.fetchrow = AsyncMock(side_effect=[_Row({"id": 1}), _Row({"id": 1})])
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "GET", "path": "/items"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["services"] == 1
    assert data["endpoints"] == 1
    assert data["edges"] == 0


# ---------------------------------------------------------------------------
# test_analyze_invalid_github_url
# ---------------------------------------------------------------------------

async def test_analyze_invalid_github_url():
    with patch("routers.analyze.clone_repo",
               side_effect=ValueError("Invalid GitHub URL: notgithub")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 422
    assert "Invalid repository URL" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_analyze_clone_failure
# ---------------------------------------------------------------------------

async def test_analyze_clone_failure():
    with patch("routers.analyze.clone_repo",
               side_effect=RuntimeError("Clone failed: authentication failed")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 400
    assert "could not be cloned" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_analyze_calls_delete_repo_on_success
# ---------------------------------------------------------------------------

async def test_analyze_calls_delete_repo_on_success(tmp_path):
    # tmp_path is empty — no service folders detected, pipeline runs but finds nothing
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo") as mock_delete, \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    mock_delete.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# test_analyze_calls_delete_repo_on_error
# ---------------------------------------------------------------------------

async def test_analyze_calls_delete_repo_on_error(tmp_path):
    # get_pool raises an unexpected exception after clone_repo succeeds.
    # ASGITransport in tests re-raises unhandled exceptions rather than
    # returning a 500 response, so we catch it with pytest.raises.
    # The finally block still runs before the exception reaches the test.
    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo") as mock_delete, \
         patch("routers.analyze.get_pool",
               new_callable=AsyncMock, side_effect=Exception("DB unavailable")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(Exception, match="DB unavailable"):
                await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    mock_delete.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# test_analyze_uses_openapi_when_present
# ---------------------------------------------------------------------------

async def test_analyze_uses_openapi_when_present(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "openapi.yaml").write_text(
        "openapi: '3.0'\ninfo:\n  title: Order Service\npaths: {}\n"
    )
    (svc_dir / "main.py").write_text("# service code")

    conn = AsyncMock()
    # service upsert returns row (parse_service found no endpoints so no endpoint upsert call)
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service",
               return_value={"service_name": "order-service", "endpoints": []}) as mock_ps, \
         patch("routers.analyze.extract_route_decorators") as mock_dec, \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    mock_ps.assert_called_once()
    mock_dec.assert_not_called()


# ---------------------------------------------------------------------------
# test_analyze_falls_back_to_decorators
# ---------------------------------------------------------------------------

async def test_analyze_falls_back_to_decorators(tmp_path):
    svc_dir = tmp_path / "user-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    conn = AsyncMock()
    # service upsert returns row (no endpoint upsert — extract_route_decorators returns [])
    conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None) as mock_ps, \
         patch("routers.analyze.extract_route_decorators", return_value=[]) as mock_dec, \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    mock_ps.assert_called_once()
    mock_dec.assert_called()


# ---------------------------------------------------------------------------
# test_analyze_skips_non_service_folders
# ---------------------------------------------------------------------------

async def test_analyze_skips_non_service_folders(tmp_path):
    # Subfolder has only a README — no .py files, no openapi.yaml
    non_svc = tmp_path / "not-a-service"
    non_svc.mkdir()
    (non_svc / "README.md").write_text("# not a service")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["services"] == 0


# ---------------------------------------------------------------------------
# test_analyze_consumer_edge_upserted
# ---------------------------------------------------------------------------

async def test_analyze_consumer_edge_upserted(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    # Service already exists with id=2; endpoint belongs to a different service (id=10)
    svc_row = _Row({"id": 2})
    ep_row = _Row({"id": 5, "method": "GET", "path": "/users/{id}", "service_id": 10})

    conn = AsyncMock()
    # fetchrow called once: service upsert returns existing row (DO UPDATE path)
    # edge insert now uses ON CONFLICT DO UPDATE via conn.execute — no pre-check fetchrow
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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 1


# ---------------------------------------------------------------------------
# test_analyze_skips_fqdn_paths_that_dont_match
# ---------------------------------------------------------------------------

async def test_analyze_skips_fqdn_paths_that_dont_match(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

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
               return_value=[{"url": "http://unknown-service/unknown/path"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0


# ---------------------------------------------------------------------------
# test_analyze_no_self_edges
# ---------------------------------------------------------------------------

async def test_analyze_no_self_edges(tmp_path):
    svc_dir = tmp_path / "item-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

    # Endpoint belongs to service_id=2, same as the caller
    svc_row = _Row({"id": 2})
    ep_row = _Row({"id": 3, "method": "GET", "path": "/items/{id}", "service_id": 2})

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
               return_value=[{"url": "http://item-service/items/1"}]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["edges"] == 0


# ---------------------------------------------------------------------------
# test_extract_path_helper
# ---------------------------------------------------------------------------

def test_extract_path_helper():
    assert _extract_path("http://user-service/users/123") == "/users/123"
    assert _extract_path("http://payment-service/payments/charge") == "/payments/charge"
    assert _extract_path("") is None
    # urlparse("http://svc").path == "" which is falsy → returns None
    assert _extract_path("http://svc") is None


# ---------------------------------------------------------------------------
# GET /services
# ---------------------------------------------------------------------------

async def test_get_services_returns_list():
    rows = [
        _Row({"id": 1, "name": "order-service", "language": "python", "repo_url": "github.com/x/y"}),
        _Row({"id": 2, "name": "user-service", "language": None, "repo_url": None}),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/services", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "order-service"


async def test_get_services_empty():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/services", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_services_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/services")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /endpoints
# ---------------------------------------------------------------------------

async def test_get_endpoints_returns_all():
    rows = [
        _Row({"id": 1, "service_id": 1, "method": "GET", "path": "/users/{id}", "spec_source": "openapi"}),
        _Row({"id": 2, "service_id": 2, "method": "POST", "path": "/orders/create", "spec_source": "decorator"}),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = _make_pool(conn)

    with patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/endpoints", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["path"] == "/users/{id}"
    assert data[0]["service_id"] == 1


async def test_get_endpoints_filters_by_service_id():
    rows = [
        _Row({"id": 1, "service_id": 1, "method": "GET", "path": "/users/{id}", "spec_source": "openapi"}),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = _make_pool(conn)

    with patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/endpoints?service_id=1", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["service_id"] == 1
    assert data[0]["path"] == "/users/{id}"


async def test_get_endpoints_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/endpoints")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /endpoints/{id}/impact-analysis
# ---------------------------------------------------------------------------

async def test_get_impact_analysis_returns_consumers():
    rows = [
        _Row({"service_name": "order-service", "call_count": 5,
              "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "source": "static"}),
        _Row({"service_name": "payment-service", "call_count": 2,
              "last_seen_at": datetime(2024, 1, 2, tzinfo=timezone.utc), "source": "static"}),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = _make_pool(conn)

    with patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/endpoints/1/impact-analysis", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["service_name"] == "order-service"
    assert data[0]["call_count"] == 5


async def test_get_impact_analysis_empty():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/endpoints/99/impact-analysis", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_impact_analysis_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/endpoints/1/impact-analysis")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /graph
# ---------------------------------------------------------------------------

async def test_get_graph_returns_nodes_and_edges():
    service_rows = [
        _Row({"id": 1, "name": "order-service"}),
        _Row({"id": 2, "name": "user-service"}),
    ]
    endpoint_rows = [
        _Row({"id": 5, "method": "GET", "path": "/users/{id}"}),
    ]
    edge_rows = [
        _Row({
            "caller_service_id": 1,
            "endpoint_id": 5,
            "endpoint_path": "/users/{id}",
            "endpoint_method": "GET",
            "call_count": 10,
            "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    # 2 service nodes + 1 endpoint node
    assert len(data["nodes"]) == 3
    assert {"id": "1", "name": "order-service"} in data["nodes"]
    assert {"id": "endpoint-5", "name": "GET /users/{id}"} in data["nodes"]
    assert len(data["edges"]) == 1
    assert data["edges"][0]["source"] == "1"
    assert data["edges"][0]["target"] == "endpoint-5"


async def test_get_graph_empty_db():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], [], []])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []


async def test_get_graph_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/graph")

    assert resp.status_code == 422


async def test_get_graph_includes_endpoint_nodes():
    service_rows = [_Row({"id": 3, "name": "payment-service"})]
    endpoint_rows = [_Row({"id": 7, "method": "POST", "path": "/payments/charge"})]
    edge_rows = [
        _Row({
            "caller_service_id": 3,
            "endpoint_id": 7,
            "endpoint_path": "/payments/charge",
            "endpoint_method": "POST",
            "call_count": 4,
            "last_seen_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
        }),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[service_rows, endpoint_rows, edge_rows])
    pool = _make_pool(conn)

    with patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/graph", headers=HEADERS)

    data = resp.json()
    node_ids = [n["id"] for n in data["nodes"]]
    assert "endpoint-7" in node_ids
    endpoint_node = next(n for n in data["nodes"] if n["id"] == "endpoint-7")
    assert endpoint_node["name"] == "POST /payments/charge"
    assert data["edges"][0]["target"] == "endpoint-7"
    assert data["edges"][0]["source"] == "3"


# ---------------------------------------------------------------------------
# Auth header enforcement
# ---------------------------------------------------------------------------

async def test_services_route_rejects_missing_github_token():
    # X-GitHub-Token is a required header — FastAPI returns 422 before any logic runs.
    # get_current_user_id is overridden by the autouse fixture so only X-GitHub-Token matters here.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/services", headers={"Authorization": "Bearer test-jwt"})

    assert resp.status_code == 422


async def test_services_route_rejects_missing_jwt(real_auth):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/services", headers={"X-GitHub-Token": "test-token"})
    assert resp.status_code == 422


async def test_services_route_rejects_invalid_jwt(real_auth):
    import auth as auth_module
    mock_jwks = MagicMock()
    mock_jwks.get_signing_key_from_jwt.side_effect = jwt.InvalidTokenError("bad token")
    with patch.object(auth_module, "_jwks_client", mock_jwks):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/services", headers={
                "X-GitHub-Token": "test-token",
                "Authorization": "Bearer invalid.jwt.token",
            })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# repo_id_from_url unit tests
# ---------------------------------------------------------------------------

def test_repo_id_from_url_https():
    assert repo_id_from_url("https://github.com/owner/name") == "owner/name"


def test_repo_id_from_url_git_suffix():
    assert repo_id_from_url("https://github.com/owner/name.git") == "owner/name"


def test_repo_id_from_url_no_scheme():
    assert repo_id_from_url("github.com/owner/name") == "owner/name"


def test_repo_id_from_url_invalid():
    with pytest.raises(ValueError):
        repo_id_from_url("notgithub.com/x/y")


# ---------------------------------------------------------------------------
# test_analyze_invalid_repo_url
# ---------------------------------------------------------------------------

async def test_analyze_invalid_repo_url():
    # repo_id_from_url raises ValueError for non-github URLs;
    # the route catches it and returns 422 before clone_repo is ever called.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            ANALYZE_URL,
            json={"repo_url": "notgithub.com/x/y"},
            headers=HEADERS,
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid repo URL"


# ---------------------------------------------------------------------------
# test_analyze_cleanup_on_db_failure
# ---------------------------------------------------------------------------

async def test_analyze_cleanup_on_db_failure(tmp_path):
    # clone_repo succeeds; get_pool raises — delete_repo must still be called.
    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo") as mock_delete, \
         patch("routers.analyze.get_pool",
               new_callable=AsyncMock, side_effect=Exception("DB unavailable")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(Exception, match="DB unavailable"):
                await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    mock_delete.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# test_analyze_sets_user_id_and_repo_id
# ---------------------------------------------------------------------------

async def test_analyze_sets_user_id_and_repo_id(tmp_path):
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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                ANALYZE_URL,
                json={"repo_url": "https://github.com/test/repo"},
                headers=HEADERS,
            )

    assert resp.status_code == 200
    # First fetchrow call is the service upsert; check its positional args
    call_pos_args = conn.fetchrow.call_args_list[0][0]
    sql = call_pos_args[0]
    assert "ON CONFLICT" in sql
    assert "user_id" in sql
    assert "repo_id" in sql
    # user_id is $4 (index 4), repo_id is $5 (index 5)
    assert call_pos_args[4] == "test-user-id"   # from conftest override
    assert call_pos_args[5] == "test/repo"       # derived from URL


# ---------------------------------------------------------------------------
# test_analyze_upsert_service_idempotent
# ---------------------------------------------------------------------------

async def test_analyze_upsert_service_idempotent(tmp_path):
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    # Both analyze calls use the upsert path; fetchrow always returns the row.
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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp1 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)
            resp2 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["services"] == 1
    assert resp2.json()["services"] == 1
    # Both calls used the upsert SQL
    sql = conn.fetchrow.call_args_list[0][0][0]
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql


# ---------------------------------------------------------------------------
# test_analyze_upsert_endpoint_idempotent
# ---------------------------------------------------------------------------

async def test_analyze_upsert_endpoint_idempotent(tmp_path):
    svc_dir = tmp_path / "my-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service")

    conn = AsyncMock()
    # First analyze: service upsert → row; endpoint upsert → row (new)
    # Second analyze: service upsert → row (DO UPDATE); endpoint upsert → None (DO NOTHING);
    #   fallback SELECT → row
    conn.fetchrow = AsyncMock(side_effect=[
        _Row({"id": 1}),  # 1st analyze — service upsert
        _Row({"id": 1}),  # 1st analyze — endpoint upsert (new)
        _Row({"id": 1}),  # 2nd analyze — service upsert (DO UPDATE)
        None,             # 2nd analyze — endpoint upsert (DO NOTHING)
        _Row({"id": 1}),  # 2nd analyze — endpoint fallback SELECT
    ])
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool(conn)

    with patch("routers.analyze.clone_repo", return_value=str(tmp_path)), \
         patch("routers.analyze.delete_repo"), \
         patch("routers.analyze.parse_service", return_value=None), \
         patch("routers.analyze.extract_route_decorators",
               return_value=[{"method": "GET", "path": "/items"}]), \
         patch("routers.analyze.extract_http_calls", return_value=[]), \
         patch("routers.analyze.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp1 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)
            resp2 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["endpoints"] == 1
    assert resp2.json()["endpoints"] == 1
    # The endpoint upsert SQL uses ON CONFLICT DO NOTHING
    endpoint_upsert_sql = conn.fetchrow.call_args_list[1][0][0]
    assert "ON CONFLICT" in endpoint_upsert_sql
    assert "DO NOTHING" in endpoint_upsert_sql


# ---------------------------------------------------------------------------
# test_analyze_upsert_edge_idempotent
# ---------------------------------------------------------------------------

async def test_analyze_upsert_edge_idempotent(tmp_path):
    svc_dir = tmp_path / "order-service"
    svc_dir.mkdir()
    (svc_dir / "main.py").write_text("# service code")

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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp1 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)
            resp2 = await client.post(ANALYZE_URL, json=PAYLOAD, headers=HEADERS)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["edges"] == 1
    assert resp2.json()["edges"] == 1
    # Edge upsert SQL uses ON CONFLICT DO UPDATE refreshing last_seen_at.
    # conn.execute is also called by set_rls_context (set_config calls), so search
    # through all execute calls to find the one that targets consumer_edges.
    edge_sql_calls = [
        c[0][0] for c in conn.execute.call_args_list if "consumer_edges" in c[0][0]
    ]
    assert len(edge_sql_calls) >= 1
    edge_sql = edge_sql_calls[0]
    assert "ON CONFLICT" in edge_sql
    assert "DO UPDATE" in edge_sql
    assert "last_seen_at" in edge_sql
