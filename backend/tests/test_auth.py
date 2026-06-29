import json
import time
import pytest
import jwt
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException

import auth as auth_module
from auth import get_current_user_id, set_rls_context


def _make_es256_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    return private_key, public_key


def _make_signing_key_mock(public_key):
    mock_key = MagicMock()
    mock_key.key = public_key
    return mock_key


# ---------------------------------------------------------------------------
# test_get_current_user_id_missing_header
# ---------------------------------------------------------------------------

async def test_get_current_user_id_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="")
    assert exc_info.value.status_code == 401
    assert "Missing Bearer token" in exc_info.value.detail


# ---------------------------------------------------------------------------
# test_get_current_user_id_no_bearer_prefix
# ---------------------------------------------------------------------------

async def test_get_current_user_id_no_bearer_prefix():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="notabearer token123")
    assert exc_info.value.status_code == 401
    assert "Missing Bearer token" in exc_info.value.detail


# ---------------------------------------------------------------------------
# test_get_current_user_id_expired_token
# ---------------------------------------------------------------------------

async def test_get_current_user_id_expired_token():
    private_key, public_key = _make_es256_keypair()
    payload = {
        "sub": "test-uuid-expired",
        "aud": "authenticated",
        "exp": int(time.time()) - 60,  # 60 seconds in the past
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")

    mock_signing_key = _make_signing_key_mock(public_key)
    with patch.object(auth_module, "_jwks_client") as mock_client:
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token expired"


# ---------------------------------------------------------------------------
# test_get_current_user_id_invalid_signature
# ---------------------------------------------------------------------------

async def test_get_current_user_id_invalid_signature():
    _, wrong_public_key = _make_es256_keypair()
    private_key, _ = _make_es256_keypair()

    payload = {
        "sub": "test-uuid-bad-sig",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")

    # Return the WRONG public key so the signature verification fails
    mock_signing_key = _make_signing_key_mock(wrong_public_key)
    with patch.object(auth_module, "_jwks_client") as mock_client:
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(authorization=f"Bearer {token}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail.startswith("Invalid token:")


# ---------------------------------------------------------------------------
# test_get_current_user_id_valid_token
# ---------------------------------------------------------------------------

async def test_get_current_user_id_valid_token():
    private_key, public_key = _make_es256_keypair()
    payload = {
        "sub": "test-uuid-1234",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")

    mock_signing_key = _make_signing_key_mock(public_key)
    with patch.object(auth_module, "_jwks_client") as mock_client:
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        result = await get_current_user_id(authorization=f"Bearer {token}")

    assert result == "test-uuid-1234"


# ---------------------------------------------------------------------------
# test_set_rls_context_executes_correct_sql
# ---------------------------------------------------------------------------

async def test_set_rls_context_executes_correct_sql():
    conn = AsyncMock()
    await set_rls_context(conn, "user-uuid-abc")

    assert conn.execute.call_count == 2

    first_call_args = conn.execute.call_args_list[0][0]
    assert "request.jwt.claims" in first_call_args[0]
    claims = json.loads(first_call_args[1])
    assert claims["sub"] == "user-uuid-abc"
    assert claims["role"] == "authenticated"

    second_call_args = conn.execute.call_args_list[1][0]
    assert "role" in second_call_args[0]
    assert "authenticated" in second_call_args[0]
