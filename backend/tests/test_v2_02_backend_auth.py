"""
Independent test suite for spec v2-02 — Backend Auth (ES256 JWT + RLS Context).

Covers:
- get_current_user_id edge cases not in existing suite
- set_rls_context SQL structure and ordering
- Per-router dependency enforcement (all 4 routers + DELETE)
- set_rls_context is actually invoked during route execution
"""

import json
import time
import pytest
import jwt
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport

import auth as auth_module
from auth import get_current_user_id, set_rls_context
from main import app


# ---------------------------------------------------------------------------
# Shared helpers — completely independent of existing test helpers
# ---------------------------------------------------------------------------

def _gen_es256_pair():
    priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
    return priv, priv.public_key()


def _sign_token(priv, payload: dict) -> str:
    return jwt.encode(payload, priv, algorithm="ES256")


def _mock_jwks(pub_key):
    """Return a context manager that patches _jwks_client to use pub_key."""
    signing_key = MagicMock()
    signing_key.key = pub_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = signing_key
    return patch.object(auth_module, "_jwks_client", mock_client)


class _FakeRow:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, k):
        return self._data[k]

    def __bool__(self):
        return True


def _make_test_pool(conn):
    pool = MagicMock()

    @asynccontextmanager
    async def _acq():
        yield conn

    pool.acquire = _acq

    @asynccontextmanager
    async def _tx():
        yield

    conn.transaction = _tx
    return pool


# ---------------------------------------------------------------------------
# get_current_user_id — header format edge cases
# ---------------------------------------------------------------------------

async def test_empty_string_authorization_raises_401():
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(authorization="")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing Bearer token"


async def test_bearer_without_trailing_space_raises_401():
    # "Bearer" with no space — doesn't start with "Bearer "
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(authorization="Bearer")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing Bearer token"


async def test_basic_auth_prefix_raises_401():
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(authorization="Basic dXNlcjpwYXNz")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing Bearer token"


async def test_token_prefix_instead_of_bearer_raises_401():
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(authorization="Token abc123")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing Bearer token"


# ---------------------------------------------------------------------------
# get_current_user_id — valid token returns correct sub
# ---------------------------------------------------------------------------

async def test_returns_sub_claim_from_valid_token():
    priv, pub = _gen_es256_pair()
    token = _sign_token(priv, {
        "sub": "supabase-uuid-abc",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    })
    with _mock_jwks(pub):
        result = await get_current_user_id(authorization=f"Bearer {token}")
    assert result == "supabase-uuid-abc"


async def test_sub_claim_returned_as_plain_string():
    priv, pub = _gen_es256_pair()
    token = _sign_token(priv, {
        "sub": "11111111-2222-3333-4444-555555555555",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    })
    with _mock_jwks(pub):
        result = await get_current_user_id(authorization=f"Bearer {token}")
    assert isinstance(result, str)
    assert result == "11111111-2222-3333-4444-555555555555"


# ---------------------------------------------------------------------------
# get_current_user_id — wrong audience rejected
# ---------------------------------------------------------------------------

async def test_wrong_audience_raises_401():
    priv, pub = _gen_es256_pair()
    # Supabase always sets aud="authenticated" — wrong audience must be rejected
    token = _sign_token(priv, {
        "sub": "some-uuid",
        "aud": "not-authenticated",
        "exp": int(time.time()) + 3600,
    })
    with _mock_jwks(pub):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert exc.value.detail.startswith("Invalid token:")


async def test_missing_audience_claim_raises_401():
    priv, pub = _gen_es256_pair()
    # No aud claim at all
    token = _sign_token(priv, {
        "sub": "some-uuid",
        "exp": int(time.time()) + 3600,
    })
    with _mock_jwks(pub):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert exc.value.detail.startswith("Invalid token:")


# ---------------------------------------------------------------------------
# get_current_user_id — expired token returns specific message
# ---------------------------------------------------------------------------

async def test_expired_token_detail_is_exactly_token_expired():
    priv, pub = _gen_es256_pair()
    token = _sign_token(priv, {
        "sub": "any-uuid",
        "aud": "authenticated",
        # Beyond the 30s clock-skew leeway in get_current_user_id (see auth.py) --
        # a token expired by only a second or two is now intentionally tolerated.
        "exp": int(time.time()) - 60,
    })
    with _mock_jwks(pub):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Token expired"


# ---------------------------------------------------------------------------
# get_current_user_id — invalid signature
# ---------------------------------------------------------------------------

async def test_signed_with_different_key_raises_401():
    priv_sign, _ = _gen_es256_pair()
    _, pub_verify = _gen_es256_pair()   # completely different key
    token = _sign_token(priv_sign, {
        "sub": "any-uuid",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    })
    with _mock_jwks(pub_verify):        # wrong public key for verification
        with pytest.raises(HTTPException) as exc:
            await get_current_user_id(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
    assert exc.value.detail.startswith("Invalid token:")


# ---------------------------------------------------------------------------
# set_rls_context — SQL call structure
# ---------------------------------------------------------------------------

async def test_set_rls_executes_exactly_two_queries():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-001")
    assert conn.execute.call_count == 2


async def test_set_rls_first_call_targets_jwt_claims_key():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-002")
    first_sql = conn.execute.call_args_list[0][0][0]
    assert "request.jwt.claims" in first_sql


async def test_set_rls_second_call_targets_role_key():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-003")
    second_sql = conn.execute.call_args_list[1][0][0]
    assert "role" in second_sql
    assert "authenticated" in second_sql


async def test_set_rls_claims_json_is_valid_and_contains_sub():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-xyz")
    claims_arg = conn.execute.call_args_list[0][0][1]
    parsed = json.loads(claims_arg)
    assert parsed["sub"] == "uid-xyz"


async def test_set_rls_claims_json_contains_role_field():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-xyz")
    claims_arg = conn.execute.call_args_list[0][0][1]
    parsed = json.loads(claims_arg)
    assert parsed["role"] == "authenticated"


async def test_set_rls_both_calls_use_transaction_local_true():
    # The SQL must include `true` as the is_local argument to set_config.
    conn = AsyncMock()
    await set_rls_context(conn, "uid-xxx")
    for c in conn.execute.call_args_list:
        sql = c[0][0]
        assert "true" in sql, f"Expected 'true' in SQL for transaction-local scope: {sql}"


async def test_set_rls_claims_call_comes_before_role_call():
    conn = AsyncMock()
    await set_rls_context(conn, "uid-order")
    calls = conn.execute.call_args_list
    first_sql = calls[0][0][0]
    second_sql = calls[1][0][0]
    assert "request.jwt.claims" in first_sql
    assert "role" in second_sql


# ---------------------------------------------------------------------------
# Router dependency enforcement — both headers required on all 4 routes
# ---------------------------------------------------------------------------

AUTH_HEADERS = {
    "X-GitHub-Token": "gh-token",
    "Authorization": "Bearer dummy-jwt",
}


async def test_services_get_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/services", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 422


async def test_services_delete_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/services/1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 422


async def test_endpoints_get_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/endpoints", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 422


async def test_impact_analysis_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/endpoints/1/impact-analysis", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 422


async def test_graph_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/graph?repo_id=owner/repo", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 422


async def test_analyze_rejects_missing_github_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/analyze",
            json={"repo_url": "github.com/x/y"},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# set_rls_context is called during route execution
# These tests verify that each router actually invokes set_rls_context,
# not just that the function exists.
# ---------------------------------------------------------------------------

async def test_services_get_invokes_set_rls_context():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_test_pool(conn)

    with patch("routers.services.set_rls_context", new_callable=AsyncMock) as spy, \
         patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/services", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    spy.assert_called_once()
    # First positional arg is the connection, second is the user_id string
    assert spy.call_args[0][1] == "test-user-id"


async def test_services_delete_invokes_set_rls_context():
    conn = AsyncMock()
    pool = _make_test_pool(conn)

    with patch("routers.services.set_rls_context", new_callable=AsyncMock) as spy, \
         patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/services/42", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    spy.assert_called_once()
    assert spy.call_args[0][1] == "test-user-id"


async def test_endpoints_get_invokes_set_rls_context():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_test_pool(conn)

    with patch("routers.endpoints.set_rls_context", new_callable=AsyncMock) as spy, \
         patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/endpoints", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    spy.assert_called_once()
    assert spy.call_args[0][1] == "test-user-id"


async def test_impact_analysis_invokes_set_rls_context():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_test_pool(conn)

    with patch("routers.endpoints.set_rls_context", new_callable=AsyncMock) as spy, \
         patch("routers.endpoints.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/endpoints/5/impact-analysis", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    spy.assert_called_once()
    assert spy.call_args[0][1] == "test-user-id"


async def test_graph_invokes_set_rls_context():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], [], []])
    pool = _make_test_pool(conn)

    with patch("routers.graph.set_rls_context", new_callable=AsyncMock) as spy, \
         patch("routers.graph.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/graph?repo_id=owner/repo", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    spy.assert_called_once()
    assert spy.call_args[0][1] == "test-user-id"


# ---------------------------------------------------------------------------
# DELETE /services/{id} — always returns {"status": "deleted"}
# ---------------------------------------------------------------------------

async def test_delete_service_returns_deleted_status_when_row_exists():
    conn = AsyncMock()
    pool = _make_test_pool(conn)

    with patch("routers.services.set_rls_context", new_callable=AsyncMock), \
         patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/services/7", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}


async def test_delete_service_returns_deleted_status_when_no_row():
    # conn.execute returns None (0 rows affected) — response must still be {"status": "deleted"}
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    pool = _make_test_pool(conn)

    with patch("routers.services.set_rls_context", new_callable=AsyncMock), \
         patch("routers.services.get_pool", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = pool
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/services/999", headers={"X-GitHub-Token": "tok"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
