# v2 Open Issues & Updated Roadmap

> Note: the previous revision of this file tracked template-literal/f-string detection and
> endpoint-level graph nodes. Both shipped as spec v2-10 and v2-11 and are merged to `main` —
> see CLAUDE.md's V2 scope table. This revision replaces that content with issues found
> afterward, while testing real repos (`Practice-Todo`, `airbnb-clone`) against the shipped v2-11 graph.

---

## Issue 1 — PATCH is not supported anywhere in `code_parser.py`

### Problem

`endpoints.method` is `VARCHAR(10)` — plenty of room for `PATCH` — and `spec_parser.py`
(OpenAPI-sourced endpoints) already allows it:

```python
_ALLOWED_METHODS = {"get", "post", "put", "delete", "patch"}
```

But `code_parser.py`, which handles every repo without an `openapi.yaml`, does not. A real
repo (`Practice-Todo`) has `patch_task` (Python decorator) and `updateTaskApi` (axios `.patch`)
— neither ever appears in the graph, as an endpoint or as a caller. They're silently dropped,
with no error and no indication anything was skipped.

### Root cause

Four separate method allow-lists in `code_parser.py`, none of which include PATCH:

- `extract_route_decorators` — `{"get", "post", "put", "delete"}`
- `extract_js_routes` (Express + Next.js route matching) — `{"GET", "POST", "PUT", "DELETE"}`
- `extract_http_calls` (`requests`/`httpx`) — `{"get", "post", "put", "delete"}`
- `_is_axios_call` — `{"get", "post", "put", "delete"}`

Three existing tests actively assert PATCH is excluded and will need to flip:
`test_extract_js_routes_express_patch_not_included`,
`test_extract_js_http_calls_axios_patch_skipped`, `test_js_express_unknown_method`.

### Fix

- Add `"patch"` / `"PATCH"` to all four allow-lists above.
- Update the CLAUDE.md schema comment: `method VARCHAR(10) NOT NULL, -- GET | POST | PUT | DELETE`
  → add PATCH to the list of documented values.
- Flip the 3 tests above to assert PATCH **is** captured instead of excluded.
- Add new round-trip tests: a `@app.patch(...)` decorator produces an endpoint row with
  `method="PATCH"`, and an `axios.patch(...)` call matches against it and produces an edge.

```
/create-spec v2-12: add PATCH to the method allow-list in backend/analysis/code_parser.py in
all four places it currently hardcodes {"get","post","put","delete"} (or the uppercase
equivalent): extract_route_decorators, extract_js_routes (both the Express and Next.js
branches), extract_http_calls, and _is_axios_call. Update backend/tests/test_code_parser.py's
test_extract_js_routes_express_patch_not_included, test_extract_js_http_calls_axios_patch_skipped,
and test_js_express_unknown_method to assert PATCH is now captured, not skipped. Add new tests:
a Python @app.patch("/tasks/{id}") decorator is captured with method="PATCH"; an
axios.patch(`/tasks/${id}`) call is captured with method="PATCH" and matches an existing PATCH
endpoint via match_url_to_endpoint. Update the CLAUDE.md schema comment for endpoints.method to
list PATCH alongside GET/POST/PUT/DELETE.
```

---

## Issue 2 — Consumer edges are visually indistinguishable ("one arrow" for many)

### Problem

A repo with 4 distinct caller functions and 4 distinct endpoints rendered as a single visible
connecting line between the two service boxes, with `×1` labels stacked on top of each other.
Impossible to tell which caller calls which endpoint just by looking.

### Root cause

Verified in `graph.py` that the data is correct — each `consumer_edges` row does produce its
own `GraphEdge`, so 4 real edges are present in the API response and 4 `rfEdges` are created
in `DependencyGraph.jsx`. The bug is purely visual: `buildElements()` stacks every leaf node at
the same `x: FILE_PADDING` within its file group (only `y` varies per leaf index), and default
React Flow smoothstep edges connect vertically-centered handles. Because the caller file group
and the provider file group sit directly above one another with the same width, every edge's
source and target X-coordinates line up almost exactly — so all 4 edges draw on top of each
other and read as one line.

### Fix

Give parallel edges distinguishable paths. Recommended combination:

- **Fan out** — offset each leaf's connection point by a small per-index amount (e.g. leaf `i`'s
  edge enters/exits at `x = leafCenterX + i * offset`) so edges between stacked columns spread
  instead of overlapping.
- **Color by caller** — assign each distinct caller (source) node id a stable color and stroke
  its outgoing edge(s) with it, so even where paths cross near the endpoints, the origin is
  identifiable at a glance.

```
/create-spec v2-13: in frontend/components/DependencyGraph.jsx, make parallel edges between
stacked leaf nodes visually distinguishable. For each edge, compute a per-index horizontal
offset based on the source leaf's position within its file group so edges fan out instead of
overlapping when source and target columns are X-aligned. Additionally assign each distinct
caller node id a stable color (e.g. hash the id to a palette index) and apply it as the edge's
stroke color via defaultEdgeOptions overrides per edge. Verify visually with a repo that has
4+ callers converging through the same file group onto 4+ endpoints in another file group —
each edge must be traceable by eye from its specific caller leaf to its specific endpoint leaf.
```

---

## Issue 3 — `call_count` is permanently stuck at 1

### Problem

Every edge in the graph shows `×1`, regardless of how many times a repo has been re-analyzed
or how many call sites exist.

### Root cause

`UPSERT_EDGE_SQL` in `analyze.py` hardcodes the inserted value:

```sql
INSERT INTO consumer_edges (..., call_count, ...) VALUES ($1, $2, NOW(), 1, $3, $4, $5)
ON CONFLICT (caller_service_id, endpoint_id)
DO UPDATE SET last_seen_at = NOW(), source = EXCLUDED.source,
              caller_file_path = EXCLUDED.caller_file_path,
              caller_function_name = EXCLUDED.caller_function_name
```

The `DO UPDATE SET` clause never touches `call_count` — it's set to `1` once on first insert
and never changes again, no matter how many times the edge is re-confirmed on re-analysis.

### Fix

Since v2 is static-analysis-only (no log ingestion), `call_count` can't mean "runtime calls per
minute" yet — but it can at least mean "confirmed present across N analyses," which is more
useful than a permanent `1`:

```sql
DO UPDATE SET call_count = consumer_edges.call_count + 1,
              last_seen_at = NOW(),
              source = EXCLUDED.source,
              caller_file_path = EXCLUDED.caller_file_path,
              caller_function_name = EXCLUDED.caller_function_name
```

```
/create-spec v2-14: fix UPSERT_EDGE_SQL in backend/routers/analyze.py (or wherever the upsert
query for consumer_edges lives) so that call_count increments on conflict instead of staying
fixed at 1 forever. Change the ON CONFLICT DO UPDATE clause to
call_count = consumer_edges.call_count + 1. Add a test that re-analyzes the same repo twice and
asserts the edge's call_count is 2 after the second analysis, not 1.
```

---

## Issue 4 — `consumer_edges` can silently drop a caller

### Problem

If two different functions (or two different files) within the *same caller service* both call
the same endpoint, only one of them ends up visible in the graph. The other is silently
overwritten with no error, no warning, and no trace it was ever detected.

### Root cause

`UNIQUE(caller_service_id, endpoint_id)` on `consumer_edges` is scoped per **service**, not per
**function**. `analyze.py`'s upsert targets exactly this constraint, so a second call site from
the same service to the same endpoint updates the *same row* — overwriting
`caller_file_path`/`caller_function_name` with whichever call site was processed last during
the folder walk. Doesn't currently manifest on `Practice-Todo` (each caller function hits a
distinct endpoint), but it's a real gap the moment two functions in one service call the same
endpoint.

### Fix

Widen the uniqueness key to include caller identity:

```sql
ALTER TABLE consumer_edges DROP CONSTRAINT consumer_edges_caller_service_id_endpoint_id_key;
ALTER TABLE consumer_edges ADD CONSTRAINT consumer_edges_caller_endpoint_function_key
  UNIQUE (caller_service_id, endpoint_id, caller_file_path, caller_function_name);
```

- Update `UPSERT_EDGE_SQL`'s `ON CONFLICT` target to match the new constraint.
- `graph.py` already keys caller nodes by `(caller_service_id, caller_file_path,
  caller_function_name)` — no change needed there. It will now correctly render multiple
  distinct caller nodes converging on the same endpoint instead of only ever keeping one.

```
/create-spec v2-15: widen the consumer_edges uniqueness constraint from
UNIQUE(caller_service_id, endpoint_id) to
UNIQUE(caller_service_id, endpoint_id, caller_file_path, caller_function_name) via a DB
migration, and update UPSERT_EDGE_SQL's ON CONFLICT target in backend/routers/analyze.py to
match. Add a regression test: two different functions in the same caller service both calling
the same endpoint must produce two distinct consumer_edges rows (and therefore two distinct
caller nodes in GET /graph), not one row where the second overwrites the first.
```

---

## Issue 5 — Untrack requires two clicks

### Problem

Clicking "Untrack" once appears to do nothing. Clicking it a second time actually removes the
repo.

### Root cause — not yet confirmed, needs a live repro

Read through the full path — `RepoList.jsx` → `deleteService`/`fetchUserRepos` in
`lib/api.js` → backend `DELETE /services/{id}` → `GET /repos` — and the logic looks correct
for a single click: delete commits inside one transaction, then repos are refetched fresh, then
`onUpdate` replaces state. No bug found by static reading. Two leading hypotheses to confirm
with the browser Network tab open on the *first* click:

1. **Stale `provider_token`.** `getAuthHeaders()` in `lib/api.js` throws "Session expired" if
   `session.provider_token` is missing. Supabase is known to drop `provider_token` from the
   session object after a background access-token refresh — it's only guaranteed present right
   after the initial OAuth callback. If the session had silently refreshed, the first click
   throws before any request is even sent, and the row just resets with an easy-to-miss error
   line.
2. **Delete succeeds, refetch fails.** `deleteService` succeeds (row is gone in the DB) but the
   following `fetchUserRepos()` call errors — `onUpdate` never runs, so the UI still shows the
   old tracked state. The second click may then be re-deleting an already-gone service (or the
   refetch simply succeeds this time).

### Fix

Reproduce first to know which one it is, then:

- If (1): don't rely on `session.provider_token` surviving a refresh — store the GitHub token
  separately at login time instead of re-reading it from the live Supabase session on every
  request.
- If (2): make the UI update optimistic — flip the row to untracked immediately after a
  successful `deleteService()` call, independent of whether the follow-up `fetchUserRepos()`
  refetch succeeds or fails.

```
/create-spec v2-16: diagnose and fix the Untrack-requires-two-clicks bug in
frontend/components/RepoList.jsx. First reproduce with the browser Network tab open on the
first click to determine whether (a) getAuthHeaders() throws before any request fires because
session.provider_token is missing after a Supabase token refresh, or (b) deleteService succeeds
but the following fetchUserRepos() call fails so the UI never updates. Fix accordingly: for (a),
stop depending on provider_token surviving a session refresh — capture and store the GitHub
token separately at login instead of re-reading it from supabase.auth.getSession() on every
call. For (b), make handleUntrack optimistically mark the row untracked immediately after
deleteService() resolves, independent of the following refetch's outcome. Add a test covering
whichever root cause is confirmed.
```

---

## Issue 6 — No way back from `/graph` to `/repos`

### Problem

`GraphPageInner.jsx`'s header has the logo, the tracked repo's name, search, and a logout
button — but nothing links back to `/repos`. The only way back is the browser back button.

### Fix

Add a nav link in the header, styled consistently with the existing header elements (next to
the logo, or as a small breadcrumb before the repo name divider).

```
/create-spec v2-17: add a "Repos" (or "← Repos") link/button to the header in
frontend/app/graph/GraphPageInner.jsx that navigates to /repos, using next/link and styled
consistently with the existing header (font-mono, alabaster/prussian color tokens, same divider
pattern already used between header sections).
```

---

## Issue 7 — `/repos` doesn't match the rest of the site's design

### Problem

`/login` (`login/page.js`) and `/graph` (`GraphPageInner.jsx`) share a consistent visual
system: a `NetworkLogo` SVG, "EndpointGraph" wordmark, `font-mono` for technical text, and
custom Tailwind tokens (`prussian-*`, `alabaster-*`, `orange`). `/repos/page.js` and
`RepoList.jsx` use none of it — a plain `<h1>`, and default Tailwind `gray-*`/`blue-600`/
`red-900`/`amber-900`/`green-900`. No header, no logo, no logout button. It reads like a
different, unstyled app bolted onto the site.

### Fix

- Give `/repos` the same header used in `GraphPageInner.jsx` (logo + wordmark + logout), plus
  the nav link added in Issue 6 (in reverse — a way to get to `/graph` for a tracked repo, if
  applicable).
- Restyle `RepoList.jsx`'s badges and buttons using the `prussian`/`alabaster`/`orange` tokens
  and `font-mono` instead of default Tailwind grays, matching `login/page.js`'s established
  visual language.

```
/create-spec v2-18: restyle frontend/app/repos/page.js and frontend/components/RepoList.jsx to
match the visual system already established in frontend/app/login/page.js and
frontend/app/graph/GraphPageInner.jsx: same NetworkLogo SVG + "EndpointGraph" wordmark header
(with a logout button, consistent with GraphPageInner's header), font-mono for technical labels,
and the prussian-*/alabaster-*/orange Tailwind color tokens in place of the current default
gray/blue/red/amber/green colors. Keep all existing behavior (Track/Re-analyze/Untrack, loading
and error states) unchanged — this is a visual-only pass.
```

---

## Issue 8 — Single-service monolith repos silently produce an empty graph

### Problem

Tracking a single-service repo (e.g. `airbnb-clone` — one root `package.json`, one Express app,
no separate frontend/backend split) analyzes successfully (`services=1`, endpoints found from
its `routes/` folder) but `/graph` shows "No graph loaded — This repo has no tracked services
yet," which reads exactly like tracking failed, even though it didn't.

### Root cause — two compounding issues

1. **By design**, `analyze.py` filters out self-calls:
   ```python
   if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
       continue
   ```
   A service can't be its own consumer. A single-service repo therefore always has exactly 0
   edges — this part is correct behavior for a tool scoped to *cross-service* consumer
   discovery (per CLAUDE.md's problem statement), not a bug.
2. **`graph.py`'s `GRAPH_QUERY` only ever produces nodes from `consumer_edges` rows**
   (`FROM consumer_edges ce JOIN services cs ... JOIN endpoints e ...`). Endpoints with zero
   callers never become nodes at all — so even the endpoints that genuinely were found for this
   repo are invisible, not just edge-less.
3. **The empty-state message is wrong for this case.** In `GraphPageInner.jsx`,
   `hasRepo = Boolean(repoId)` only checks whether a `repo` query param exists in the URL — it
   never checks the DB. So "This repo has no tracked services yet" is shown even when the repo
   *was* tracked successfully and simply has no consumer edges. The message actively misleads
   the user into thinking tracking failed.

### Fix

- **Messaging (small, do first):** distinguish "not tracked" from "tracked but zero edges" from
  "no repo selected." `GET /graph` (or a lightweight companion field) should tell the frontend
  whether the repo has tracked services and endpoints even when `edges` is empty, so
  `GraphPageInner.jsx` can show something like *"`airbnb-clone` has 1 tracked service and 6
  endpoints, but no other tracked service calls them — this tool tracks cross-service
  consumers, not a single monolith's own routes."*
- **Orphan endpoints (bigger, needs a decision first):** optionally render endpoints with zero
  incoming edges as unconnected nodes, so a tracked repo always shows *something* even with no
  edges yet. Requires `graph.py` to also query `endpoints` directly (not only via
  `consumer_edges`), and `DependencyGraph.jsx`/`buildElements()` to handle nodes with no edges
  at all (currently every leaf's existence is inferred from the edge rows). Don't spec this half
  until it's decided whether orphan endpoints should be visible at all — flag for a product
  decision, not an immediate implementation.

```
/create-spec v2-19: fix the misleading empty-graph message in
frontend/app/graph/GraphPageInner.jsx. Currently hasRepo = Boolean(repoId) only checks the URL
query param, so "This repo has no tracked services yet" shows even when the repo was tracked
successfully but has zero consumer_edges (e.g. a single-service monolith, where analyze.py's
self-call exclusion means it can never have edges). Extend GET /graph's response (or add a
lightweight field to it) to report whether the repo has at least one tracked service/endpoint
even when edges is empty, and show a distinct message for that case explaining that
EndpointGraph tracks cross-service consumers, not a single service's own routes. Do not change
analyze.py's self-call exclusion — that behavior is correct and intentional.
```

---

## Issue 9 — `APIRouter(prefix=...)` and `include_router(..., prefix=...)` are invisible to the parser, causing both missed edges and *false* edges

### Problem

Tracked `next-craft/NextPrep` (a real FastAPI + Next.js app — cloned and inspected directly, not
guessed). Backend has 21 real endpoints across 6 routers. The rendered graph showed exactly one
endpoint node, `get_college — GET /{slug}`, with 5 "callers" (`Home`, `sitemap`, `CollegesPage`,
`ListingsPage`, `UserProfilePage`). Tracing each of those 5 callers back to its actual source
line shows **none of them are really calling `GET /colleges/{slug}`**:

| Caller | File | What it actually calls |
|---|---|---|
| `sitemap` | `app/sitemap.js` | `fetch(\`${API_URL}/listings\`)` |
| `CollegesPage` | `app/(marketplace)/colleges/page.jsx` | `fetch(\`${API_URL}/colleges?has_listings=1\`)` |
| `ListingsPage` | `app/(marketplace)/listings/page.jsx` | `fetch(\`${API_URL}/listings?${params}\`)` |
| `UserProfilePage` | `app/(marketplace)/users/[id]/page.jsx` | `fetch(\`${API_URL}/listings?seller_id=${id}\`)` |

Every one of these is a **false positive** — the graph is not just incomplete, it is actively
wrong about which service calls which endpoint.

### Root cause

`backend/app/routers/colleges.py` declares:

```python
router = APIRouter(prefix="/colleges", tags=["colleges"])

@router.get("/{slug}", response_model=CollegeDetailOut)
async def get_college(...): ...
```

and `backend/app/main.py` mounts it with a second prefix:

```python
app.include_router(colleges.router, prefix="/v1")
```

The real path is `/v1/colleges/{slug}`. `extract_route_decorators` in `code_parser.py` only
looks at the string literal passed directly to `@router.get(...)` in isolation — it has no
concept of the `prefix=` kwarg on the `APIRouter(...)` construction, and no concept of
`include_router`'s `prefix=` at all (which lives in an entirely different file). The path gets
stored as just `/{slug}`.

`url_matcher.match_url_to_endpoint` turns that into the regex `[^/]+` — "matches any single path
segment." Every other truncated endpoint collapses to the *same* regex (`/{listing_id}` →
`[^/]+`, `/{user_id}` → `[^/]+`, `/listings?has_listings=1` after stripping → `[^/]+`, etc.), so
any single-segment call from *any* caller can match *any* one of these endpoints — whichever
happens to come first in `known_endpoints`' unspecified row order (`analyze.py` queries
`endpoints` with no `ORDER BY`). The 5 matches shown are not 5 correct edges to `get_college`;
they're 5 arbitrary collisions.

This affects all 21 endpoints in this repo: every router in `backend/app/routers/` is declared
with `APIRouter(prefix=...)` and mounted via `include_router(..., prefix="/v1")` — the standard,
idiomatic FastAPI pattern for any app with more than one router.

### Fix

Needs cross-file resolution, not a one-line change:

- **Python:** parse `<var> = APIRouter(prefix="...")` in each router file to get the router-local
  prefix, then parse `include_router(<module>.<var>, prefix="...")` calls in the entrypoint file
  (`main.py`/`app.py`) to get the mount prefix. Concatenate `mount_prefix + router_prefix +
  route_path` when recording the endpoint. Requires linking the router variable's *declaring*
  file to its *usage* file.
- **JS/Express:** the equivalent gap exists for `express.Router()` + `app.use("/prefix", router)`
  — not yet confirmed against a real repo, but the same class of bug.
- Once real prefixes are captured, `known_endpoints` should also be sorted deterministically
  (e.g. by longest-path-first, or scoped by originating repo) so degenerate regex collisions
  between *correctly extracted* endpoints can't silently pick the wrong one either.

```
/create-spec v2-20: teach backend/analysis/code_parser.py to resolve the full mount path of a
FastAPI route instead of just the string literal on the @router decorator. Parse
`<var> = APIRouter(prefix="...")` assignments per router file to capture a router-local prefix.
Separately parse `app.include_router(<module>.<var>, prefix="...")` calls in the service's
entrypoint file (main.py/app.py) to capture the mount-level prefix, linking router variable names
across files. In analyze.py, compose the final endpoint path as
mount_prefix + router_prefix + decorator_path. Add tests using a repo shape with two files: a
routers/things.py declaring `router = APIRouter(prefix="/things")` with `@router.get("/{id}")`,
and a main.py with `app.include_router(things.router, prefix="/v1")` — assert the stored endpoint
path is `/v1/things/{id}`, not `/{id}`. Flag (do not fix in this spec) that known_endpoints in
analyze.py has no ORDER BY, so once truncation is fixed, verify no two distinct endpoints still
collapse to the same match_url_to_endpoint regex in the test fixture.
```

---

## Issue 10 — Wrapped axios instances (`axios.create()`) are invisible to the parser

### Problem

NextPrep's frontend centralizes all API calls through one shared axios instance —
`frontend/lib/api.js`:

```javascript
const api = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL })
// ... auth interceptor attaches the Supabase JWT ...
export default api
```

Every call site imports this and calls `api.get(...)`, `api.post(...)`, etc. — e.g.
`frontend/lib/queries.js`:

```javascript
queryFn: async () => (await api.get('/users/me')).data
```

**22 such calls across 10 files** (`queries.js`, `ListingFilters.jsx`, and others). All 22 are
silently dropped — zero edges. Grepping the entire frontend for the literal pattern the parser
actually looks for (`axios.get(...)`, `axios.post(...)`, etc.) returns **0 matches** — this
codebase's real axios usage has a 0% detection rate. This is exactly the pattern this project's
own `frontend/lib/api.js` uses per `CLAUDE.md` — a wrapped instance is the standard way to
centralize `baseURL` and auth headers, not an edge case.

### Root cause

`_is_axios_call` in `code_parser.py`:

```python
def _is_axios_call(match) -> bool:
    ...
    if lib_node.text.decode("utf-8") != "axios":
        return False
    return method_node.text.decode("utf-8") in {"get", "post", "put", "delete", "patch"}
```

This only matches calls of the literal shape `axios.get(...)` — never an aliased/wrapped
instance like `api.get(...)`, `http.post(...)`, `client.delete(...)`. The only reason NextPrep's
graph shows *anything* is that its 12 raw `fetch(...)` calls are at least attempted (and, per
Issue 9, still miswired).

### Fix

Two options, different precision/complexity tradeoffs:

1. **Broad:** match any `<identifier>.get/post/put/delete/patch(<string-or-template>)` regardless
   of the object name — mirrors how `extract_js_routes`'s Express query is already intentionally
   broad about object names (`app`, `router`, `api`, `v1`, etc. are all accepted). Risk: false
   positives from unrelated objects with common method names (e.g. `cache.get(key)`,
   `map.get(key)` — anything with a single string/template argument named like an HTTP verb).
2. **Precise:** trace `import axios from 'axios'` + `<var> = axios.create(...)` per file to build
   a set of known axios-instance variable names, and match calls only against that set. More
   accurate, but is the same cross-file resolution problem as Issue 9 (the instance is created in
   `lib/api.js` and imported everywhere it's used).

Given Issue 9 already requires building cross-file resolution machinery, doing both fixes
together (and sharing that infrastructure) is likely more efficient than two separate passes.

```
/create-spec v2-21: extend backend/analysis/code_parser.py's axios call detection beyond the
literal identifier "axios". Implement option 2 from v2-open-issues.md Issue 10: for each JS/TS
file (or better, each service's full file set), find `import axios from 'axios'` plus
`<var> = axios.create(...)` assignments (including cases where the instance is exported from one
file, e.g. lib/api.js, and imported by name into every call site) to build a set of known
axios-instance identifiers, then match `<var>.get/post/put/delete/patch(...)` calls against that
set instead of the hardcoded "axios" string. Add a test: a lib/api.js-style file exporting
`const api = axios.create(...)` as default, and a separate file `import api from './lib/api'`
calling `api.get('/things')`, must produce a captured HTTP call the same way a direct
`axios.get('/things')` call would. If full cross-file tracing proves too large for one spec,
fall back to option 1 (broad identifier match) as an interim step and note the false-positive
tradeoff in the spec's test plan.
```

---

## Issue 11 — `extract_js_routes`' Express-style detection fabricates endpoints out of ordinary method calls

### Problem

After fixing Issues 9 and 10, re-tracking `next-craft/NextPrep` showed **48 tracked endpoints** —
implausible for a repo with 21 real backend routes (Issue 9's count) and a frontend that exposes
none of its own. Directly scanning NextPrep's frontend with `extract_js_routes` confirms it://
**29 fabricated endpoints** come out of files that declare zero real routes, e.g.:

```python
extract_js_routes('lib/queries.js')
# -> {'method': 'GET', 'path': '/users/me', ...}        # really: api.get('/users/me'), an HTTP call
# -> {'method': 'GET', 'path': '/conversations', ...}    # really: api.get('/conversations')
extract_js_routes('components/auth/auth-card.jsx')
# -> {'method': 'GET', 'path': 'error', ...}              # really: params.get('error')
extract_js_routes('components/listings/CreateListingForm.jsx')
# -> {'method': 'GET', 'path': 'title', ...}              # really: fd.get('title') (a FormData read)
```

None of these are route declarations. `api.get(...)` is an HTTP *call* (already correctly captured
by `extract_js_http_calls`/Issue 10). `params.get('error')`/`fd.get('title')` are
`URLSearchParams`/`FormData` reads that have nothing to do with HTTP routing at all.

### Root cause

The Express-style query in `extract_js_routes` (Case A) only requires **one string argument**:

```python
express_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier)
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path))
""")
```

A real Express route registration is always `app.get(path, handler)` — **two** arguments, the
second being a handler function. This query never checks for that second argument; it matches
any `<identifier>.get/post/put/delete/patch(<string>)` call, full stop. The existing tests
`test_js_express_route_captures_handler_identifier` /
`test_js_express_route_arrow_handler_no_function_name` already exercise a handler being present,
but only to *optionally* populate `function_name` — never as a precondition for matching at all.

This inflates `endpoint_count` with garbage, pollutes the `endpoints` table, and (per Issue 12
below) can pollute `known_endpoints` with paths that coincidentally collide with real endpoints
from other services.

### Fix

Require the handler-shaped second argument before treating a call as a route declaration:

```python
express_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier)
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path
    .
    [(identifier) (arrow_function) (function_expression)] @handler))
""")
```

This still accepts arbitrary object names (per the existing intentional design for `app`,
`router`, `v1`, etc.) but now requires a plausible handler as the very next argument — which
`api.get(url)`, `params.get(key)`, and `fd.get(key)` never have (they pass exactly one argument).

```
/create-spec v2-22: fix extract_js_routes' Express-style detection (Case A) in
backend/analysis/code_parser.py to require a handler-shaped second argument
(identifier, arrow_function, or function_expression immediately following the path string)
before treating a call as a route declaration -- not just any <identifier>.get/post/put/delete/
patch(<string>) call. Add regression tests: api.get('/things') (an HTTP client call through a
single-argument call), params.get('key') (URLSearchParams), and fd.get('key') (FormData) must
all produce zero results from extract_js_routes. A real two-argument Express route
(app.get('/things', handler)) must still be captured exactly as before, including function_name
extraction from an identifier or arrow-function handler.
```

---

## Issue 12 — Exact endpoint-path matching breaks once endpoint paths carry a mount prefix the caller's `baseURL` supplies invisibly

### Problem

This is a direct side effect of the Issue 9 fix. Real NextPrep backend endpoint (correct, post-fix):
`/v1/users/me`. Real NextPrep frontend call site: `api.get('/users/me')`, where `api`'s `baseURL`
is `process.env.NEXT_PUBLIC_API_URL` — an environment variable whose value (invisible to static
source analysis) plausibly already ends in `/v1`. Verified directly:

```python
match_url_to_endpoint('/users/me', ['/v1/users/me'])  # -> None
```

Before Issue 9, endpoint paths were stored so truncated (`/me`, missing both the router-local and
mount prefixes) that they degraded into overly generic single-segment regexes and *accidentally*
matched all sorts of things (Issue 9's own false-positive writeup). Now that paths are accurate,
`url_matcher`'s `re.fullmatch` requires an exact match end to end — and any caller whose HTTP
client supplies its mount prefix through an opaque `baseURL`/env var (the standard pattern for
literally every non-trivial frontend, including this project's own `lib/api.js`) will never
literally spell out that prefix in its call-site string. Net effect: correctly-extracted backend
paths + correctly-extracted frontend calls (Issues 9 and 10 both fixed) still produce **zero
edges**, because matching itself is now too strict for the single most common real-world shape.

### Root cause

`match_url_to_endpoint` requires `re.fullmatch` — the call's path and the known endpoint's path
(after `{param}` substitution) must match end to end, with no tolerance for the known endpoint
having extra leading segments the caller never wrote out. There is currently no mechanism to
express "the caller's path is a suffix of the real path, because a chunk of the real path lives
in an env var the parser can't see."

### Fix

Needs a second matching pass, not a replacement of the first — full match should still be tried
first (it's unambiguous when it succeeds), falling back to suffix matching only when it fails:

- Split both the call's path and each known path into `/`-separated segments.
- If the call's segments are a **contiguous trailing slice** of the known path's segments
  (matching `{param}` segments the same way `match_url_to_endpoint` already does), consider it a
  match.
- This is inherently riskier than exact matching (a short caller path like `/me` could spuriously
  suffix-match many endpoints) — mitigate by requiring the call's segment count to be at least 2,
  or by preferring the fewest-extra-leading-segments match when several candidates suffix-match,
  and by keeping method-based filtering (already in `analyze.py`) as the first-pass narrowing
  before this runs at all.

```
/create-spec v2-23: add a suffix-matching fallback to backend/analysis/url_matcher.py's
match_url_to_endpoint for the case where a known endpoint path has more leading segments than the
caller's literal call-site path (because the caller's HTTP client baseURL supplies a mount prefix
invisible to static analysis -- see v2-open-issues.md Issue 12). Try exact re.fullmatch first, as
today; if nothing matches, fall back to comparing the call's path segments against every known
path's trailing segments of the same length (substituting {param} segments the same way), and
return the match with the fewest unaccounted-for leading segments if more than one candidate
suffix-matches. Add tests: '/users/me' must match a known '/v1/users/me' (single leading extra
segment); a short caller path like '/me' should NOT spuriously match an unrelated multi-segment
endpoint just because it happens to be a trailing substring; and an exact match must still win
over a suffix match when both are available for the same call.
```

---

## Issue 13 — Graph empty state shows hardcoded placeholder service names for every repo

### Problem

Tracking `next-craft/NextPrep` (or any repo) and landing on the empty-state screen always shows
the exact same three decorative boxes: `user-service`, `order-service`, `payment-service` —
regardless of which repo was actually tracked or what its real services are named. This is what
originally raised the "are you hardcoding something for whatever repo I give?" question — and for
this specific piece of UI, yes.

### Root cause

`frontend/app/graph/GraphPageInner.jsx`'s `EmptyState` component:

```jsx
{['user-service', 'order-service', 'payment-service'].map((name) => (
  <div key={name} ...>{name}</div>
))}
```

These are CLAUDE.md's own demo `sample-services` names (see the "Sample services (demo graph)"
section), hardcoded directly into the empty-state illustration during the Issue 8 fix. They were
meant as generic decoration ("here's what a graph *would* look like"), but read as if the tool is
showing fake/stubbed data for the real, just-tracked repo — especially confusing right next to a
message that already correctly names the real repo and its real (if currently wrong, per Issues
11/12) service/endpoint counts.

### Fix

Either remove the illustration entirely (the text message alone already explains the empty state
clearly), or make it generic/abstract (unlabeled boxes, or a muted diagram) instead of using
concrete service names that could be mistaken for real data.

```
/create-spec v2-24: remove or genericize the hardcoded ['user-service', 'order-service',
'payment-service'] placeholder illustration in EmptyState (frontend/app/graph/GraphPageInner.jsx).
These are CLAUDE.md's demo sample-services names and are shown identically for every repo
regardless of its real services, which reads as fake/stubbed data next to the real, dynamically
computed empty-state message. Either drop the box illustration entirely, or replace it with
visibly-abstract placeholders (e.g. unlabeled/greyed boxes) that can't be mistaken for real
per-repo data.
```
