# Spec v2-09 — Delete Service (Untrack)

## Goal
`DELETE /services/{id}` lets a user untrack a repo — it verifies the service belongs to the requesting user (404 if not), deletes it, and relies on the existing `ON DELETE CASCADE` on `endpoints` and `consumer_edges` to clean up dependent rows.

## Depends on
- v2-01 (db migration — `services.user_id` column + cascades exist)
- v2-02 (backend auth — `get_github_token`, `get_current_user_id`, `set_rls_context`)

## Context
`backend/routers/services.py` already has a `DELETE /services/{service_id}` route, but it runs `DELETE FROM services WHERE id = $1` unconditionally — it never checks that the service belongs to the requesting user before deleting, and it never returns 404 for a missing/foreign service. RLS (`set_rls_context`) would prevent the DB from touching another user's row, but with no ownership pre-check the endpoint currently returns `{"status": "deleted"}` even when nothing was deleted (id doesn't exist, or belongs to another user) — the caller can't distinguish success from silent no-op. This spec adds the explicit ownership check called for in CLAUDE.md's "two independent layers" decision: application-layer `WHERE user_id = $n` in addition to DB-layer RLS.

`frontend/lib/api.js` already has `deleteService(serviceId)` (lines 68-76) sending `DELETE` to `/services/{serviceId}` with both auth headers via `getAuthHeaders()`, matching the required shape exactly — no frontend changes are needed for this spec.

## Files to edit
- `backend/routers/services.py` — rewrite `delete_service` to check ownership first and return 404 if not found
- `backend/tests/test_routes.py` — add delete-service test cases (no existing tests cover this route)

## Files to create
None.

## Implementation details

### backend/routers/services.py

Add `HTTPException` to the FastAPI import and rewrite `delete_service`:

```python
from fastapi import APIRouter, Depends, HTTPException
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
            row = await conn.fetchrow(
                "SELECT id FROM services WHERE id = $1 AND user_id = $2",
                service_id, user_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Service not found")
            await conn.execute("DELETE FROM services WHERE id = $1", service_id)
    return {"status": "deleted"}
```

Notes:
- `user_id` from `Depends(get_current_user_id)` is a `str` (the JWT `sub` claim); asyncpg binds it against the `UUID` column by value — no manual cast needed, consistent with how `set_rls_context` already uses it elsewhere in this codebase.
- The ownership `SELECT` and the `DELETE` happen inside the same transaction as `set_rls_context`, so RLS is active for both statements — a request for a service owned by a different user finds no row at the `SELECT` (RLS filters it out even before the `user_id = $2` predicate is evaluated) and gets 404, never reaching the `DELETE`.
- The plain `DELETE FROM services WHERE id = $1` (no `AND user_id = $2`) is intentional and safe: by this point ownership is already confirmed by the preceding `SELECT`, and RLS still enforces `user_id = auth.uid()` on the `DELETE` as a second layer per CLAUDE.md's "two independent layers" decision.
- No explicit deletes of `endpoints` or `consumer_edges` — `ON DELETE CASCADE` on both tables' foreign keys to `services.id` handles it.
- Do not add a response model — the route already returns a plain `dict`, matching the `{status: "deleted"}` shape in the API contract exactly as-is.

### frontend/lib/api.js

No changes needed. `deleteService(serviceId)` (already at lines 68-76) already:
- Sends `DELETE` to `${NEXT_PUBLIC_API_URL}/services/${serviceId}`
- Attaches both auth headers via `getAuthHeaders()`
- Throws via `extractError(res)` on non-2xx responses (this will surface the new 404 message correctly with no further changes)
- Returns `res.json()`

Verify this matches during implementation; do not duplicate or rewrite it.

## Test cases

Backend (`backend/tests/test_routes.py`) — follow the existing mocking pattern in this file: patch `routers.services.get_pool` with `new_callable=AsyncMock` (same as `test_get_services_returns_list`, test_routes.py:390), use `_make_pool(conn)` for `conn.transaction()`, wrap every mocked `conn.fetchrow` return value in the file's `_Row(...)` helper (test_routes.py:16) rather than a raw dict, and use the same `HEADERS = {"X-GitHub-Token": "test-token"}` constant already defined at test_routes.py:11 for tests that don't need to exercise the `Authorization` header itself.

- `test_delete_service_success` — `conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))`, `conn.execute = AsyncMock(return_value=None)`; `DELETE /services/1` with `headers=HEADERS` returns `200` and `{"status": "deleted"}`; assert `conn.execute` was called with `"DELETE FROM services WHERE id = $1"` and `1`
- `test_delete_service_not_found` — `conn.fetchrow = AsyncMock(return_value=None)`; `DELETE /services/999` with `headers=HEADERS` returns `404`; assert `conn.execute` (the actual delete) was never called
- `test_delete_service_wrong_user` — `conn.fetchrow = AsyncMock(return_value=None)` (simulating RLS/`user_id` filter excluding a service owned by another user); `DELETE /services/1` with `headers=HEADERS` returns `404` — same behavior as not-found, since ownership violations must not be distinguishable from missing rows
- `test_delete_service_requires_github_token` — omit `X-GitHub-Token` header (send only `{"Authorization": "Bearer test-jwt"}`); expect `422` — no DB mocking needed, matches the pattern of `test_services_route_rejects_missing_github_token` (test_routes.py:651)
- `test_delete_service_requires_auth_header(real_auth)` — **must** take the `real_auth` fixture (`backend/tests/conftest.py`) as a parameter, which pops the `get_current_user_id` override for the duration of the test. Without it, the `override_get_current_user_id` autouse fixture in `conftest.py` replaces `get_current_user_id` with `lambda: "test-user-id"` for every test by default, so omitting `Authorization` would not actually trigger the missing-header path. Send only `{"X-GitHub-Token": "test-token"}` (no `Authorization` header); expect `422` — mirrors `test_services_route_rejects_missing_jwt(real_auth)` (test_routes.py:660)
- `test_delete_service_checks_ownership_before_delete` — set `conn.fetchrow = AsyncMock(return_value=_Row({"id": 1}))` and `conn.execute = AsyncMock(return_value=None)`, issue `DELETE /services/1`, then assert ordering via `conn.mock_calls`: find the index of the `fetchrow` call and the index of the `execute` call in `conn.mock_calls` and assert `fetchrow`'s index is smaller; also assert `conn.fetchrow.call_args.args == (1, "test-user-id")` to confirm both bind params are passed

## Done when
- [ ] `backend/routers/services.py`'s `delete_service` selects `id FROM services WHERE id = $1 AND user_id = $2` first and raises `HTTPException(404)` if no row is found
- [ ] `DELETE FROM services WHERE id = $1` only runs after the ownership check passes
- [ ] `set_rls_context(conn, user_id)` remains the first statement in the transaction
- [ ] Route returns `{"status": "deleted"}` on success, matching the API contract exactly
- [ ] No explicit deletes of `endpoints`/`consumer_edges` — cascade handles it
- [ ] `frontend/lib/api.js`'s `deleteService(serviceId)` verified to already match the required request shape (DELETE + both headers) — confirmed no edit needed
- [ ] `test_delete_service_requires_auth_header` uses the `real_auth` fixture so the missing-`Authorization` path is actually exercised (not masked by the autouse `override_get_current_user_id` fixture)
- [ ] Every test case listed passes
- [ ] No hardcoded credentials anywhere
- [ ] Follows conventions from CLAUDE.md (raw asyncpg, no ORM, RLS context set first, both auth headers required)
