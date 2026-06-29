from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import ServiceOut

router = APIRouter()


@router.get("/services", response_model=list[ServiceOut])
async def get_services(
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            rows = await conn.fetch(
                "SELECT id, name, language, repo_url FROM services ORDER BY id"
            )
    return [
        ServiceOut(id=r["id"], name=r["name"], language=r["language"], repo_url=r["repo_url"])
        for r in rows
    ]


@router.delete("/services/{service_id}")
async def delete_service(
    service_id: int,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            await conn.execute("DELETE FROM services WHERE id = $1", service_id)
    return {"status": "deleted"}
