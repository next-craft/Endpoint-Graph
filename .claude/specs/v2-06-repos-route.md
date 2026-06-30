# Spec v2-06 — GET /repos Route

## Goal
Implement `GET /repos` in `backend/routers/repos.py` that proxies the GitHub API repo list and annotates each repo with its tracked status, `last_analyzed_at`, and `service_id` from the database.

## Depends on
- v2-01 (DB migration — `user_id`, `repo_id`, `last_analyzed_at` columns on `services`)
- v2-02 (backend auth — `get_github_token`, `get_current_user_id`, `set_rls_context`)

## Context
The frontend `/repos` page needs a combined view: the user's GitHub repos (from GitHub API) merged with which ones are tracked in EndpointGraph (from the DB). This route does that merge on the backend so the frontend makes one call instead of two. It uses the GitHub token to call `https://api.github.com/user/repos` and then queries `public.services` to annotate each repo with tracking state. RLS ensures users only see their own service rows.

## Files to create
- `backend/routers/repos.py` — FastAPI router with the single `GET /repos` route

## Files to edit
- `backend/main.py` — import and register the `repos` router with prefix `/repos`
- `backend/models.py` — add `RepoOut` Pydantic model

## Implementation details

### backend/models.py

Add `RepoOut` alongside the existing models:

```python
class RepoOut(BaseModel):
    name: str
    full_name: str
    private: bool
    updated_at: str
    tracked: bool
    last_analyzed_at: datetime | None
    service_id: int | None
```

`service_id` is the `public.services.id` of the tracked service for this repo, or `None` when `tracked=False`. The frontend needs it to call `DELETE /services/{id}`.

### backend/routers/repos.py

```python
from fastapi import APIRouter, Depends
import httpx

from auth import get_github_token, get_current_user_id, set_rls_context
from database import get_pool
from models import RepoOut

router = APIRouter()
```

One route:

#### `GET /repos`

```python
@router.get("", response_model=list[RepoOut])
async def list_repos(
    github_token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
```

**Known limitation:** `per_page=100` returns at most one page. Users with 101+ repos will see a truncated list. Pagination is out of v2 scope.

Steps:
1. Call `https://api.github.com/user/repos?per_page=100&type=owner` using `httpx.AsyncClient` with these headers:
   - `Authorization: Bearer {github_token}`
   - `User-Agent: EndpointGraph` (GitHub requires a non-empty User-Agent or it returns 403)
   - `Accept: application/vnd.github.v3+json`
   - Use `async with httpx.AsyncClient() as client:` so the connection is properly closed.
   - Wrap the call in `try/except httpx.RequestError` — raise `HTTPException(status_code=502, detail="GitHub API unreachable")` if it fires.
2. Parse the JSON response as a list of repo objects. Extract per repo: `name`, `full_name`, `private`, `updated_at`. If the list is empty, skip the DB query and return `[]`.
3. Collect all `full_name` values into a list, then query the DB in one round-trip using the asyncpg pool:

```python
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
            user_id, full_names
        )
```

   - `full_names` = list of `full_name` strings from step 2.
   - Build a lookup dict: `{row["repo_id"]: {"id": row["id"], "last_analyzed_at": row["last_analyzed_at"]} for row in rows}`.
4. For each GitHub repo, look up its `full_name` in the dict:
   - If found: `tracked=True`, `last_analyzed_at=row["last_analyzed_at"]`, `service_id=row["id"]`
   - If not found: `tracked=False`, `last_analyzed_at=None`, `service_id=None`
5. Return the list of `RepoOut` objects in the same order as the GitHub API returned them.

**Error handling:**
- If GitHub returns 401 or 403, raise `HTTPException(status_code=401, detail="Invalid GitHub token")`.
- If GitHub returns any other non-2xx, raise `HTTPException(status_code=502, detail="GitHub API error")`.
- If `httpx` throws `httpx.RequestError` (timeout, DNS failure, etc.), raise `HTTPException(status_code=502, detail="GitHub API unreachable")`.
- DB errors propagate as-is (FastAPI returns 500).

**httpx dependency:** `httpx` must already be in `requirements.txt`. If not, add it and pin the version.

### backend/main.py

```python
from routers import repos   # add alongside existing router imports
app.include_router(repos.router, prefix="/repos")
```

## Test cases

All tests go in `backend/tests/test_routes.py` (or a new `test_repos_route.py` if that file is getting large).

- `test_get_repos_returns_list` — mock GitHub API to return two repos; mock DB to return one tracked service matching `full_name` of the first repo; assert response has two items, first has `tracked=True` with correct `service_id` and `last_analyzed_at`, second has `tracked=False` with nulls.
- `test_get_repos_all_untracked` — mock GitHub to return repos, mock DB to return empty rows; assert all items have `tracked=False`, `service_id=None`, `last_analyzed_at=None`.
- `test_get_repos_all_tracked` — mock GitHub to return two repos, mock DB to return two matching services; assert both items have `tracked=True`.
- `test_get_repos_github_401` — mock GitHub to return 401; assert route raises HTTP 401.
- `test_get_repos_github_403` — mock GitHub to return 403; assert route raises HTTP 401 (same mapping as 401).
- `test_get_repos_github_502` — mock GitHub to return 500; assert route raises HTTP 502.
- `test_get_repos_github_connection_error` — mock `httpx.AsyncClient.get` to raise `httpx.RequestError`; assert route raises HTTP 502 with detail "GitHub API unreachable".
- `test_get_repos_empty_github_response` — mock GitHub to return `[]`; assert route returns `[]` without querying the DB.
- `test_get_repos_missing_github_token` — call without `X-GitHub-Token` header; assert 422 (FastAPI validation).
- `test_get_repos_missing_auth_header` — call without `Authorization` header; assert 422.

## Done when

- [ ] `backend/routers/repos.py` exists and exports `router`
- [ ] `GET /repos` is registered in `main.py` under prefix `/repos`
- [ ] `RepoOut` is defined in `models.py` with all seven fields
- [ ] Route calls GitHub API with `Authorization: Bearer {token}`, `User-Agent: EndpointGraph`, and `Accept: application/vnd.github.v3+json` headers, and `per_page=100&type=owner` query params
- [ ] DB connection is acquired via `async with pool.acquire() as conn: async with conn.transaction():` pattern
- [ ] `set_rls_context(conn, user_id)` is called as the first statement inside the transaction
- [ ] DB query uses a single `ANY($2::text[])` lookup (not N separate queries)
- [ ] `tracked`, `last_analyzed_at`, and `service_id` are correctly set based on DB results
- [ ] GitHub 401/403 returns HTTP 401; other GitHub non-2xx errors return HTTP 502
- [ ] `httpx.RequestError` (connection/timeout failure) returns HTTP 502
- [ ] Empty GitHub response returns `[]` without querying the DB
- [ ] All test cases listed above pass
- [ ] `httpx` is present in `requirements.txt` with a pinned version
- [ ] No hardcoded credentials anywhere
- [ ] Follows conventions from CLAUDE.md (raw asyncpg, no ORM)
