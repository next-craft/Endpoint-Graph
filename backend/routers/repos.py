from fastapi import APIRouter, Depends, HTTPException
import httpx

from auth import get_github_token, get_current_user_id, set_rls_context
from database import get_pool
from models import RepoOut

router = APIRouter()


@router.get("", response_model=list[RepoOut])
async def list_repos(
    github_token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
) -> list[RepoOut]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user/repos",
                params={"per_page": 100, "type": "owner"},
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "User-Agent": "EndpointGraph",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="GitHub API unreachable")

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Invalid GitHub token")
    if not response.is_success:
        raise HTTPException(status_code=502, detail="GitHub API error")

    github_repos = response.json()
    if not github_repos:
        return []

    full_names = [repo["full_name"] for repo in github_repos]

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            rows = await conn.fetch(
                """
                SELECT id, repo_id, last_analyzed_at
                FROM services
                WHERE user_id = $1
                  AND repo_id = ANY($2::text[])
                """,
                user_id, full_names,
            )

    tracked_map = {
        row["repo_id"]: {"id": row["id"], "last_analyzed_at": row["last_analyzed_at"]}
        for row in rows
    }

    result = []
    for repo in github_repos:
        tracked_info = tracked_map.get(repo["full_name"])
        result.append(RepoOut(
            name=repo["name"],
            full_name=repo["full_name"],
            private=repo["private"],
            updated_at=repo["updated_at"],
            tracked=tracked_info is not None,
            last_analyzed_at=tracked_info["last_analyzed_at"] if tracked_info else None,
            service_id=tracked_info["id"] if tracked_info else None,
        ))

    return result
