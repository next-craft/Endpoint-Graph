from fastapi import FastAPI, Depends
from httpx import AsyncClient, ASGITransport
from main import app
from auth import get_github_token

# Separate app for auth dependency tests — never mutate the global app
_auth_app = FastAPI()


@_auth_app.get("/protected")
async def protected_route(token: str = Depends(get_github_token)):
    return {"token": token}


async def test_health_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_no_auth_required():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


async def test_get_github_token_missing_header():
    async with AsyncClient(transport=ASGITransport(app=_auth_app), base_url="http://test") as client:
        response = await client.get("/protected")
    assert response.status_code == 422


async def test_get_github_token_empty_string():
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-GitHub-Token": ""})
    assert response.status_code == 401
    assert response.json()["detail"] == "GitHub token required"
