import os
import json
import asyncpg
import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

_jwks_client = PyJWKClient(os.getenv("SUPABASE_JWKS_URL")) if os.getenv("SUPABASE_JWKS_URL") else None


async def get_github_token(x_github_token: str = Header(alias="X-GitHub-Token")):
    if not x_github_token:
        raise HTTPException(status_code=401, detail="GitHub token required")
    return x_github_token


async def get_current_user_id(authorization: str = Header()) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if _jwks_client is None:
        raise HTTPException(status_code=503, detail="Auth service not configured")
    token = authorization[7:]
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            leeway=30,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    return payload["sub"]


async def set_rls_context(conn: asyncpg.Connection, user_id: str) -> None:
    claims = json.dumps({"sub": user_id, "role": "authenticated"})
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", claims)
    await conn.execute("SELECT set_config('role', 'authenticated', true)")
