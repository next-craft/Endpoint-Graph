# Spec v2-08 — Scoped Graph

## Goal
`GET /graph` requires a `repo_id` query param and returns only the services, endpoints, and consumer edges belonging to that repo (for the authenticated user); the frontend `/graph` page reads `repo` from the URL and re-fetches on every mount, so the graph persists across a page refresh.

## Depends on
- v2-01 (db migration — `services.repo_id` column exists)
- v2-02 (backend auth — `get_github_token`, `get_current_user_id`, `set_rls_context`)
- v2-06 (repos route — establishes `repo_id` format as GitHub `full_name`, e.g. `iamaryan07/sample-services`)
- v2-07 (repos page — `RepoList` already does `router.push(\`/graph?repo=${repo.full_name}\`)` on Track)

## Context
Today `backend/routers/graph.py` returns every service/endpoint/edge in the database with no repo scoping at all — the SQL has no `WHERE` clause on `repo_id`. The frontend `app/graph/page.js` still uses the v1 flow: an inline `RepoInput` box that calls `triggerAnalysis` and refetches the graph via a button click, with no relationship to the URL. Since v2-07 already redirects to `/graph?repo=owner/name` after tracking, the graph page must switch to being driven by that URL param instead of local component state, and the backend must actually filter by it.

Per CLAUDE.md's key decision "Endpoint-level graph nodes," the final node/edge shape (3-level service → file → endpoint/caller nesting) is out of scope here — that is v2-11. This spec keeps the **current** two-level node shape (`GraphNode{id, name}` for both services and endpoints, `GraphEdge{source, target, endpoint_path, endpoint_method, call_count, last_seen_at}` already defined in `backend/models.py`) and only adds repo scoping. No changes to `backend/models.py` are needed — the existing `GraphNode`/`GraphEdge`/`GraphOut` models already match the required shape.

## Files to edit
- `backend/routers/graph.py` — add required `repo_id` query param, filter all three queries by it
- `backend/tests/test_routes.py` — update the `GET /graph` test block to pass `repo_id`, add new scoping/required-param tests
- `frontend/lib/api.js` — make `fetchGraph(repoId)` require `repoId` (no more optional/no-param mode)
- `frontend/app/graph/page.js` — replace with a thin Suspense wrapper (see below)
- `frontend/__tests__/GraphPage.test.jsx` — update to mock `useSearchParams`/mount-based fetch instead of clicking an "Analyze" button

## Files to create
- `frontend/app/graph/GraphPageInner.jsx` — the actual graph page logic (moved out of `page.js` so `useSearchParams` can be wrapped in `<Suspense>`, matching the existing pattern in `frontend/app/auth/callback/page.js` + `AuthCallbackInner.jsx`)

## Implementation details

### backend/routers/graph.py

```python
from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()


@router.get("/graph", response_model=GraphOut)
async def get_graph(
    repo_id: str,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            service_rows = await conn.fetch(
                "SELECT id, name FROM services WHERE repo_id = $1 ORDER BY id",
                repo_id,
            )
            endpoint_rows = await conn.fetch(
                "SELECT DISTINCT e.id, e.method, e.path"
                " FROM endpoints e"
                " JOIN consumer_edges ce ON ce.endpoint_id = e.id"
                " JOIN services s ON s.id = e.service_id"
                " WHERE s.repo_id = $1"
                " ORDER BY e.id",
                repo_id,
            )
            edge_rows = await conn.fetch(
                "SELECT ce.caller_service_id, ce.endpoint_id,"
                " e.path AS endpoint_path, e.method AS endpoint_method,"
                " ce.call_count, ce.last_seen_at"
                " FROM consumer_edges ce"
                " JOIN endpoints e ON e.id = ce.endpoint_id"
                " JOIN services cs ON cs.id = ce.caller_service_id"
                " WHERE cs.repo_id = $1",
                repo_id,
            )

    service_nodes = [GraphNode(id=str(r["id"]), name=r["name"]) for r in service_rows]
    endpoint_nodes = [
        GraphNode(id=f"endpoint-{r['id']}", name=f"{r['method']} {r['path']}")
        for r in endpoint_rows
    ]
    nodes = service_nodes + endpoint_nodes

    edges = [
        GraphEdge(
            source=str(r["caller_service_id"]),
            target=f"endpoint-{r['endpoint_id']}",
            endpoint_path=r["endpoint_path"],
            endpoint_method=r["endpoint_method"],
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
        )
        for r in edge_rows
    ]
    return GraphOut(nodes=nodes, edges=edges)
```

Notes:
- `repo_id: str` has no default and no path placeholder in `"/graph"`, so FastAPI treats it as a **required query param** — a request without `?repo_id=...` gets a `422`, same status code family as the existing missing-header case.
- `repo_id` must be declared before the `Depends(...)` parameters in the function signature (Python requires non-default params before default params).
- `set_rls_context(conn, user_id)` remains the first statement inside the transaction, unchanged.
- The three existing queries are otherwise untouched — only a `WHERE repo_id = $1` (or the corresponding join) is added to each so that services/endpoints/edges from a *different* repo (even one owned by the same user) never appear together.
- `edge_rows` filters on the caller's `repo_id` (`cs.repo_id`), matching CLAUDE.md's canonical graph query, while `endpoint_rows` filters on the endpoint owner's `repo_id` (`s.repo_id`). This asymmetry is intentional, not a bug: a `consumer_edge` is only ever created between services discovered in the same `analyze()` run (see `analyze.py`), so a caller and the endpoint it calls always share the same `repo_id` — filtering either side of a given query yields the same result set.

### backend/tests/test_routes.py

Update the existing `GET /graph` tests to pass `?repo_id=...` and add coverage for the new scoping behavior. `conn.fetch` is called 3 times in order (services, endpoints, edges) via `side_effect=[...]`, same as today.

- `test_get_graph_returns_nodes_and_edges` — update the request to `client.get("/graph?repo_id=iamaryan07/sample-services", headers=HEADERS)`; assertions unchanged otherwise
- `test_get_graph_empty_db` — update the request to include `?repo_id=owner/empty-repo`; `conn.fetch` still returns `[[], [], []]`
- `test_get_graph_requires_token` — unchanged (still omits `X-GitHub-Token`, still expects 422), but the URL must include a valid `?repo_id=...` so the 422 is attributable to the missing header, not the missing query param
- `test_get_graph_requires_repo_id` (new) — calls `client.get("/graph", headers=HEADERS)` with no `repo_id` query param at all, expects `422`
- `test_get_graph_scopes_queries_by_repo_id` (new) — asserts that `conn.fetch` was called with `repo_id` as a bind parameter on all three calls, e.g. `conn.fetch.call_args_list[0].args == ("SELECT id, name FROM services WHERE repo_id = $1 ORDER BY id", "iamaryan07/sample-services")` (match whichever exact SQL string is implemented — assert the `repo_id` value is passed, not necessarily the literal SQL text)
- Rename `test_get_graph_includes_endpoint_nodes` → keep as-is but add `?repo_id=...` to its request

### frontend/lib/api.js

Change `fetchGraph` from optional to required:

```javascript
export async function fetchGraph(repoId) {
  const headers = await getAuthHeaders()
  const url = `${process.env.NEXT_PUBLIC_API_URL}/graph?repo_id=${encodeURIComponent(repoId)}`
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}
```

Remove the `repoId = null` default and the branching URL construction — every caller must now supply a `repoId`.

### frontend/app/graph/page.js

Replace the entire file with a thin wrapper, following the same pattern already used in `frontend/app/auth/callback/page.js`:

```jsx
import { Suspense } from 'react'
import GraphPageInner from './GraphPageInner'

export default function GraphPage() {
  return (
    <Suspense fallback={null}>
      <GraphPageInner />
    </Suspense>
  )
}
```

### frontend/app/graph/GraphPageInner.jsx (new file)

Moves all the logic currently in `page.js` into this file — including the `const DependencyGraph = dynamic(() => import('@/components/DependencyGraph'), { ssr: false })` line, the `NetworkLogo`/`EmptyState` helper components, and the `SERVICE_NODE_STYLE`/`ENDPOINT_NODE_STYLE` constants — with these changes:

- `'use client'` at the top (unchanged requirement)
- Import `useSearchParams` from `next/navigation`; read `const repoId = useSearchParams().get('repo')`
- Remove the `RepoInput` import and its usage in the header — analysis is now triggered from `/repos` (v2-07), not from the graph page. Keep the rest of the header (logo, `SearchBar`, logout button).
- Add a `useEffect(() => { ... }, [repoId])` that:
  - If `repoId` is falsy: do not call `fetchGraph`; set `graphError` to `null`, leave `nodes`/`edges` empty so `EmptyState` renders. Update `EmptyState`'s copy to say something like "No repo selected — go to /repos and track one" (a link to `/repos` is acceptable but not required)
  - If `repoId` is present: set `graphLoading = true`, call `fetchGraph(repoId)`, transform the response into React Flow nodes/edges exactly as `handleAnalysisComplete` does today (split `graphData.nodes` into service vs `endpoint-` prefixed nodes, build `rfNodes`/`rfEdges`, keep `SERVICE_NODE_STYLE`/`ENDPOINT_NODE_STYLE` positioning logic unchanged), then `setGraphLoading(false)`
  - On fetch failure: `setGraphError(err.message)`
  - Reset `selectedEndpoint` and `search` at the start of each fetch (same as `handleAnalysisComplete` does today)
- `handleNodeClick` and the `ImpactPanel` wiring are unchanged — endpoint nodes still exist in this spec's shape, so clicking an `endpoint-*` node still opens `ImpactPanel` exactly as it does today.
- Because `repoId` comes from `useSearchParams()` (URL-derived), refreshing the page re-runs the same `useEffect` with the same `repoId` and re-fetches from the DB — this is what makes the graph persist across a refresh, per the goal of this spec.
- Show the tracked repo's name somewhere in the header (e.g. next to the logo) using `repoId` directly, e.g. `<span>{repoId}</span>`, so the user can see which repo they're viewing.

### frontend/__tests__/GraphPage.test.jsx

Update to reflect the new mount-driven flow instead of the button-click flow:

- Remove the `jest.mock('@/components/RepoInput', ...)` block and the `triggerAnalysis` mock/import — no longer used by this page
- Add a mock built on a `jest.fn()` so individual tests can override its return value:
  ```javascript
  const mockUseSearchParams = jest.fn(() => new URLSearchParams('repo=iamaryan07/sample-services'))
  jest.mock('next/navigation', () => ({
    useSearchParams: () => mockUseSearchParams(),
  }))
  ```
  A plain arrow function passed directly to `jest.mock`'s factory cannot be overridden per test — it must wrap a `jest.fn()` like above so tests can call `mockUseSearchParams.mockReturnValueOnce(...)`.
- `import GraphPage from '@/app/graph/GraphPageInner'` (test the inner component directly, no need to exercise the `Suspense` wrapper)
- Rewrite `test_graph_page_transforms_fetchGraph_response` to: mock `fetchGraph` to resolve on render (no button click needed), `await waitFor` for `order-service` to appear, assert `fetchGraph` was called with `'iamaryan07/sample-services'`
- Rewrite `test_graph_page_shows_error_when_fetchGraph_fails` similarly — no click, just render and wait for the error text
- Keep `test_handleNodeClick_ignores_service_nodes` and `test_handleNodeClick_sets_state_for_endpoint_nodes`, removing the `fireEvent.click(screen.getByText('Analyze'))` lines (fetch now happens automatically on mount)
- Add `test_graph_page_shows_empty_state_when_no_repo_param` — before rendering, call `mockUseSearchParams.mockReturnValueOnce(new URLSearchParams())`, render, assert `fetchGraph` was never called and the empty-state message is shown

## Test cases

Backend (`backend/tests/test_routes.py`):
- `test_get_graph_returns_nodes_and_edges` — passes `repo_id`, still asserts full node/edge shape
- `test_get_graph_empty_db` — passes `repo_id`, still asserts empty arrays
- `test_get_graph_requires_token` — valid `repo_id` present, no `X-GitHub-Token` header, expects 422
- `test_get_graph_requires_repo_id` — valid headers, no `repo_id` query param, expects 422
- `test_get_graph_scopes_queries_by_repo_id` — asserts `repo_id` value is passed as a bind parameter to all three `conn.fetch` calls
- `test_get_graph_includes_endpoint_nodes` — passes `repo_id`, unchanged assertions otherwise

Frontend (`frontend/__tests__/GraphPage.test.jsx`):
- `test_graph_page_transforms_fetchGraph_response` — renders with `repo=iamaryan07/sample-services` in the URL, asserts `fetchGraph` called with that value and nodes render without any click
- `test_graph_page_shows_error_when_fetchGraph_fails` — same, asserts error text appears on mount
- `test_handleNodeClick_ignores_service_nodes` — unchanged behavior, no click-to-fetch needed first
- `test_handleNodeClick_sets_state_for_endpoint_nodes` — unchanged behavior, no click-to-fetch needed first
- `test_graph_page_shows_empty_state_when_no_repo_param` — no `repo` param in URL, `fetchGraph` never called, empty state shown

## Done when
- [ ] `backend/routers/graph.py` requires `repo_id` as a query param and filters all three queries by it
- [ ] `backend/models.py` is unchanged (existing `GraphNode`/`GraphEdge`/`GraphOut` already match)
- [ ] `frontend/lib/api.js`'s `fetchGraph(repoId)` requires `repoId`, no optional/no-param branch remains
- [ ] `frontend/app/graph/page.js` is a `Suspense`-wrapped thin export; `frontend/app/graph/GraphPageInner.jsx` contains the logic
- [ ] `GraphPageInner` reads `repo` from `useSearchParams()`, fetches on mount via `useEffect`, and refreshing the page re-fetches the same repo's graph without losing it
- [ ] `RepoInput` is no longer used on the graph page (tracking/analysis happens on `/repos` per v2-07)
- [ ] Endpoint-node click still opens `ImpactPanel` exactly as before (no regression — this spec keeps the current two-level node shape; the 3-level service→file→endpoint model is deferred to v2-11)
- [ ] Every test case listed passes
- [ ] No TypeScript — all files are `.js` or `.jsx`
- [ ] No hardcoded credentials anywhere
- [ ] Follows conventions from CLAUDE.md (raw asyncpg, `set_rls_context` first in transaction, `ssr:false` dynamic import for `DependencyGraph` unchanged, ES2022 JS)
