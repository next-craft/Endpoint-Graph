from typing import Optional
from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import EndpointOut, ConsumerOut

router = APIRouter()


@router.get("/endpoints", response_model=list[EndpointOut])
async def get_endpoints(
    service_id: Optional[int] = None,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            if service_id is not None:
                rows = await conn.fetch(
                    "SELECT id, service_id, method, path, spec_source"
                    " FROM endpoints WHERE service_id = $1 ORDER BY id",
                    service_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, service_id, method, path, spec_source"
                    " FROM endpoints ORDER BY id"
                )
    return [
        EndpointOut(
            id=r["id"],
            service_id=r["service_id"],
            method=r["method"],
            path=r["path"],
            spec_source=r["spec_source"],
        )
        for r in rows
    ]


@router.get("/endpoints/{id}/impact-analysis", response_model=list[ConsumerOut])
async def get_impact_analysis(
    id: int,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            rows = await conn.fetch(
                "SELECT s.name AS service_name, ce.call_count, ce.last_seen_at, ce.source"
                " FROM consumer_edges ce"
                " JOIN services s ON s.id = ce.caller_service_id"
                " WHERE ce.endpoint_id = $1"
                " ORDER BY ce.call_count DESC",
                id,
            )
    return [
        ConsumerOut(
            service_name=r["service_name"],
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
            source=r["source"],
        )
        for r in rows
    ]
