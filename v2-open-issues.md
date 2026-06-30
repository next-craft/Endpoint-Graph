# v2 Open Issues & Updated Roadmap

---

## Issue 1 — Template literals and f-strings are skipped (real calls go undetected)

### Problem

The current static analysis skips any URL that is not a plain string literal.

```js
// DETECTED ✓
fetch("http://user-service/users/1")
axios.get("http://payment-service/charge")

// NOT DETECTED ✗  (template literal with env var)
fetch(`${process.env.NEXT_PUBLIC_API_URL}/users`)
fetch(`${BASE_URL}/users/${id}/profile`)
```

```python
# DETECTED ✓
requests.get("http://user-service/users/1")

# NOT DETECTED ✗  (f-string)
requests.get(f"http://user-service/users/{user_id}")
requests.get(f"{SERVICE_HOST}/users/{user_id}")
```

In practice, almost every real frontend and real microservice uses env vars or variables for the host. Only the PATH portion is static. This means the tool produces zero edges for most real codebases.

### Root cause

`extract_js_http_calls` only queries for `(string)` nodes — it ignores `template_string` nodes entirely.
`extract_http_calls` calls `_is_fstring()` and skips anything that returns true.

### Fix

The host portion of a URL is dynamic (runtime env var or service variable) — we can never know it statically. We don't need it. The URL matcher only looks at the **path** portion anyway.

The path is always the static part of the URL. For example:

```js
`${process.env.NEXT_PUBLIC_API_URL}/users`
//  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ dynamic host   /users ← static path we need
```

```js
`${BASE_URL}/users/${id}/profile`
//  ^^^^^^^ dynamic    ^^^ dynamic   /users/ and /profile ← static parts we need
```

**Algorithm for template literals (JS):**
1. Walk the `template_string` node's children
2. Collect text content nodes (literal string parts)
3. Collect `template_substitution` positions (where `${...}` was)
4. Reconstruct: join literal parts with `{param}` placeholder where substitutions were
5. From the reconstructed string, extract the path portion — the segment that starts with `/`
   (everything before the first `/` is the host, which we discard)

Result: `` `${BASE_URL}/users/${id}/profile` `` → `/users/{param}/profile`

**Algorithm for f-strings (Python):**
Same approach — the tree-sitter `f_string` node exposes the interpolated segments. Collect literal parts, replace `{...}` interpolations with `{param}`, extract path starting at `/`.

Result: `f"http://svc/users/{user_id}"` → `/users/{user_id}`

Note: `{user_id}` is actually better than `{param}` here — the variable name tells us what kind of value it is and matches more naturally against registered paths like `/users/{id}`.

**Implementation scope (new spec v2-10):**
- `code_parser.py`: new helper `_extract_template_path(node, lang) -> str | None`
  - for JS: walks `template_string` children, collects literal parts + substitution positions
  - for Python: walks `f_string` children the same way
- `extract_js_http_calls`: add a second tree-sitter query matching `(template_string)` as the URL argument; run extracted paths through `_extract_template_path`
- `extract_http_calls`: remove the `_is_fstring` skip; instead extract path from f-string nodes
- The rest of the pipeline (URL matching → edge creation) is unchanged — it already operates on paths

---

## Issue 2 — Graph shows one node per service (not useful for monolithic repos)

### Problem

Current graph: **one node per service folder**.

For a monolithic repo with `frontend/` and `backend/`:
```
[ frontend ] ─────────────── [ backend ]
```

This tells you almost nothing. You can't see which file in the frontend is calling which endpoint, or from where in the backend each endpoint is served.

### Node hierarchy

Three levels of nesting:

```
Service group  (container — the service/folder name)
  └── File group  (container — relative file path)
        └── Endpoint node  (leaf — function name + METHOD /path)
```

On the **provider side** (backend files), each leaf node is one endpoint the function exposes:
```
┌─── routers/users.py ─────────────────────────────┐
│  ┌────────────────────────┐  ┌──────────────────┐ │
│  │ get_user               │  │ list_users       │ │
│  │ GET /users/{id}        │  │ GET /users       │ │
│  └────────────────────────┘  └──────────────────┘ │
└──────────────────────────────────────────────────┘
```

On the **caller side** (frontend files), each leaf node is one function that makes an HTTP call:
```
┌─── lib/api.js ───────────────────────────────────┐
│  ┌────────────────────────┐  ┌──────────────────┐ │
│  │ fetchUser              │  │ submitOrder      │ │
│  │ → GET /users/{id}      │  │ → POST /orders   │ │
│  └────────────────────────┘  └──────────────────┘ │
└──────────────────────────────────────────────────┘
```

Edges connect **leaf-to-leaf**: a caller function node → a provider endpoint node.

---

### What the graph should look like

**Case 1 — One caller file calling two different backend files**

```
╔══════════════════════════════════════════════════════════════╗
║  frontend/                                                   ║
║  ┌─── lib/api.js ──────────────────────────────────────┐    ║
║  │  ┌──────────────────────┐  ┌──────────────────────┐ │    ║
║  │  │ fetchUser            │  │ submitOrder          │ │    ║
║  │  │ → GET /users/{id}    │  │ → POST /orders       │ │    ║
║  │  └──────────┬───────────┘  └──────────┬───────────┘ │    ║
║  └─────────────╪────────────────────────╪───────────────┘    ║
╚════════════════╪════════════════════════╪═══════════════════╝
                 │                        │
╔════════════════╪════════════════════════╪═══════════════════╗
║  backend/      │                        │                    ║
║  ┌─── routers/users.py ───┐  ┌─── routers/orders.py ───┐   ║
║  │  ┌──────────────────┐  │  │  ┌───────────────────┐  │   ║
║  │  │ get_user         │◀─╫──╫──┘ create_order       │  │   ║
║  │  │ GET /users/{id}  │  │  │  │ POST /orders       │◀─╫──┘║
║  │  └──────────────────┘  │  │  └───────────────────┘  │   ║
║  │  ┌──────────────────┐  │  └─────────────────────────┘   ║
║  │  │ list_users       │  │                                 ║
║  │  │ GET /users       │  │                                 ║
║  │  └──────────────────┘  │                                 ║
║  └────────────────────────┘                                 ║
╚═════════════════════════════════════════════════════════════╝
```

`routers/users.py` has **two endpoint nodes** (`get_user` and `list_users`). `list_users` has no incoming edges — nobody calls it yet. That absence is itself useful information.

---

**Case 2 — Multiple callers converge on the same endpoint node**

This is the core use case: "if I change `GET /users/{id}`, what breaks?"

```
╔═══════════════════════════════════════════════════════════════╗
║  frontend/                                                    ║
║  ┌─── lib/api.js ─────────────┐  ┌─── pages/orders.js ────┐  ║
║  │  ┌──────────────────────┐  │  │  ┌──────────────────┐  │  ║
║  │  │ fetchUser            │  │  │  │ loadOrderUser    │  │  ║
║  │  │ → GET /users/{id}    │  │  │  │ → GET /users/... │  │  ║
║  │  └──────────┬───────────┘  │  │  └────────┬─────────┘  │  ║
║  └─────────────╪──────────────┘  └───────────╪────────────┘  ║
╚════════════════╪═════════════════════════════╪═══════════════╝
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
╔═══════════════════════════════════════════════════════════════╗
║  backend/                                                     ║
║  ┌─── routers/users.py ──────────────────────────────────┐   ║
║  │  ┌───────────────────────────────────────────────┐    │   ║
║  │  │  get_user    GET /users/{id}                  │    │   ║
║  │  └───────────────────────────────────────────────┘    │   ║
║  └────────────────────────────────────────────────────┘   ║
╚═══════════════════════════════════════════════════════════════╝
```

Two caller function nodes converge on one endpoint node. Clicking `get_user` opens the impact panel showing both `fetchUser` and `loadOrderUser` with their call counts. No need to hunt — the graph shows it directly.

---

**Case 3 — Microservices repo (sample-services)**

```
╔══════════════════════════════════════════╗
║  order-service/                          ║
║  ┌─── service/client.py ───────────────┐ ║
║  │  ┌──────────────────────────────┐   │ ║
║  │  │ get_user_details             │ ──╫─╫──── GET /users/{id} ──────▶ ┌──────────────────────────┐
║  │  │ → GET /users/{id}            │   │ ║                              │ user-service/            │
║  │  └──────────────────────────────┘   │ ║                              │ routers/users.py         │
║  │  ┌──────────────────────────────┐   │ ║                              │  ┌─────────────────────┐ │
║  │  │ charge_payment               │ ──╫─╫── POST /payments/charge ──▶  │  │ get_user            │ │
║  │  │ → POST /payments/charge      │   │ ║                              │  │ GET /users/{id}     │ │
║  │  └──────────────────────────────┘   │ ║                              │  └─────────────────────┘ │
║  └─────────────────────────────────────┘ ║                              └──────────────────────────┘
╚══════════════════════════════════════════╝
                                                      ▼
                                           ┌──────────────────────────────┐
                                           │ payment-service/             │
                                           │ routes/payments.py           │
                                           │  ┌────────────────────────┐  │
                                           │  │ charge                 │  │
                                           │  │ POST /payments/charge  │  │
                                           │  └────────────────────────┘  │
                                           └──────────────────────────────┘
```

Each function in `client.py` is a leaf node. Each has one outgoing edge to the specific endpoint node it calls.

---

**Layout algorithm**

Auto-positioned top-to-bottom using dagre:

- Services that **only call** (no exposed endpoints matched by any caller) → top
- Services that **only expose** (no outgoing calls detected) → bottom
- Services that do **both** → middle

Within a service group, file groups are arranged in a row. Within a file group, endpoint/function nodes are stacked vertically. The group boxes auto-resize to fit their contents.

### What this requires

**DB migration — four new columns:**
```sql
ALTER TABLE endpoints ADD COLUMN file_path VARCHAR(500);
-- relative path to the file this endpoint was declared in (e.g. routers/users.py)

ALTER TABLE endpoints ADD COLUMN function_name VARCHAR(255);
-- name of the function/handler (e.g. get_user, GET for Next.js exports)

ALTER TABLE consumer_edges ADD COLUMN caller_file_path VARCHAR(500);
-- relative path to the file that contains this HTTP call

ALTER TABLE consumer_edges ADD COLUMN caller_function_name VARCHAR(255);
-- name of the function that contains the HTTP call (e.g. fetchUser, charge_payment)
```

**code_parser.py — capture function names**

*Provider side — route functions:*

- `extract_route_decorators(file_path)`: the tree-sitter `DECORATOR_QUERY` matches `decorated_definition` nodes. The `function_definition` child of that node has a `name` identifier — extend the query to capture it. Return dict gains `"function_name"` key.
  ```python
  # query extension:
  (decorated_definition
    (decorator ...)
    (function_definition
      name: (identifier) @fn_name))
  ```
- `extract_js_routes(file_path)`:
  - Express routes: second argument to `app.get(path, handler)` is sometimes a named identifier (`getUser`) — capture it. If the handler is an anonymous arrow function, `function_name = None`.
  - Next.js routes: the exported function name IS the method name (`GET`, `POST`) — already captured, use it as `function_name`.

*Caller side — enclosing function:*

- `extract_http_calls(file_path)` (Python): after matching the call node, walk up through `.parent` links to find the nearest `function_definition` ancestor. Return its `name` identifier as `"caller_function_name"`. If the call is at module scope (no enclosing function), `caller_function_name = None`.
- `extract_js_http_calls(file_path)` (JS/TS): same — walk up from the `call_expression` node through parent nodes to find the nearest `function_declaration`, `method_definition`, or arrow function assigned to a variable. Return the function/variable name as `"caller_function_name"`. **Return type changes from `list[str]` to `list[dict]`** with keys `{"url", "file_path", "caller_function_name"}` — this is a breaking change, update `analyze.py` and all tests accordingly.

**analyze.py — store file_path and function_name:**
- When inserting endpoints: pass `file_path` (relative to `folder_path`) and `function_name`
- When inserting edges: pass `caller_file_path` (relative to `folder_path`) and `caller_function_name`
- Update the upsert SQL to include the new columns

**graph.py — endpoint-level nodes:**

Each node in the graph is one endpoint (provider side) or one caller function (caller side):

- **Provider endpoint node**: `id = "ep:{endpoint_id}"`, label top line = `function_name` (or `method + " " + path` if no function name), label bottom line = `METHOD /path`. Carries metadata: `file_path`, `service_name`, `service_id`.
- **Caller function node**: `id = "caller:{caller_service_id}:{caller_file_path}:{caller_function_name}"`, label = `caller_function_name` (or file path if no function name). Carries metadata: `caller_file_path`, `service_name`, `service_id`.
- **Edges**: source = caller node id, target = provider endpoint node id.
- **Grouping metadata on each node**: `service_name` (for the outer container) and `file_path` (for the inner container) — the frontend uses these to build the nested layout, not separate node types.

**Frontend — 3-level React Flow hierarchy:**
- `DependencyGraph.jsx`: three levels — service group nodes (parent), file group nodes (parent, child of service), endpoint/function leaf nodes (child of file).
- Use React Flow's `parentId` feature for nesting. Each leaf node has `parentId = "{service}:{file}"`, each file group node has `parentId = "{service}"`.
- Auto-layout with dagre on the service-group level only; within each service group, stack leaf nodes vertically.
- `ImpactPanel.jsx`: update to show `caller_function_name` and `caller_file_path` per consumer, not just `service_name`.

**Implementation scope: new spec v2-11**
Touches: DB migration (4 columns), code_parser.py (extend queries + enclosing-function walk), analyze.py (pass new columns), graph.py (endpoint-level nodes with grouping metadata), DependencyGraph.jsx (3-level nesting), ImpactPanel.jsx (function-level consumer detail)

---

## Issue 3 — Gaps in v2-07 spec (deleteService and triggerAnalysis)

### 3a — `deleteService(serviceId)` has no source for `serviceId`

`RepoOut` (returned by `GET /repos`) currently has:
```python
{ name, full_name, private, updated_at, tracked, last_analyzed_at }
```

No `service_id`. So when the user clicks Untrack, the frontend has no idea which service ID to pass to `DELETE /services/{id}`.

**Fix:** Add `service_id: int | None` to `RepoOut` — `None` when `tracked=false`, the DB service ID when `tracked=true`. This needs to be added in v2-06 when the DB query already joins on services.

### 3b — `triggerAnalysis(repo.clone_url)` has a `.git` suffix

`clone_url` from the GitHub API is `https://github.com/owner/repo.git`. The cloner strips `.git` so it works, but it's cleaner to pass `repo.html_url` (`https://github.com/owner/repo`, no suffix) or construct `https://github.com/${repo.full_name}`.

**Fix:** Use `repo.html_url` in the Track and Re-analyze button handlers.

---

## Updated /create-spec commands (v2-06 onward)

Run these in order. Each one depends on the previous being implemented and tested.

---

### v2-06

```
/create-spec v2-06: implement GET /repos in backend/routers/repos.py. The route requires both X-GitHub-Token and Authorization headers. It calls https://api.github.com/user/repos?per_page=100&type=owner using the GitHub token. For each repo returned, query the DB (with RLS context set) to check if any service with repo_id = repo.full_name exists for this user — if yes, fetch its id and last_analyzed_at. Return a list of RepoOut: {name: str, full_name: str, private: bool, updated_at: str, tracked: bool, last_analyzed_at: datetime | None, service_id: int | None}. service_id is the DB id of the tracked service (null when tracked=false) — the frontend needs it for DELETE /services/{id}. Register the router in main.py. Add RepoOut to models.py.
```

---

### v2-07

```
/create-spec v2-07: implement the frontend /repos page at app/repos/page.js. It is a protected route — redirect to /login if no Supabase session. On mount, call fetchUserRepos() from lib/api.js and render the result using a RepoList.jsx component. Each repo row shows: repo name, a "Private" or "Public" badge, last analyzed timestamp (or "Never" if null), and action buttons. If tracked=false: one "Track" button. If tracked=true: a "Re-analyze" button and an "Untrack" button. Track calls triggerAnalysis(repo.html_url) then redirects to /graph?repo=repo.full_name. Re-analyze calls triggerAnalysis(repo.html_url) and refreshes the row in place. Untrack calls deleteService(repo.service_id) then removes the repo from the list. Show a loading spinner while fetching. Show an inline error message if any API call fails. fetchUserRepos and triggerAnalysis are already in lib/api.js — do not re-implement them. Add deleteService(serviceId) to lib/api.js if not already there.
```

---

### v2-08

```
/create-spec v2-08: update GET /graph in backend/routers/graph.py to require a repo_id query param (format: owner/name). The route requires both auth headers. Set RLS context before any DB query. The SQL query joins consumer_edges, services, and endpoints, filtering WHERE services.repo_id = $1. Return GraphOut: nodes is one entry per distinct service (id = str(service.id), name = service.name), edges is one entry per consumer_edge (source = str(caller_service_id), target = str(endpoint's service_id), endpoint_path, endpoint_method, call_count, last_seen_at). On the frontend, update app/graph/page.js to read the repo query param from the URL (?repo=owner/name), call fetchGraph(repoId) on mount, transform the response into React Flow node and edge objects, and pass them to DependencyGraph. The graph must persist on page refresh because repoId comes from the URL not component state. Update fetchGraph(repoId) in lib/api.js to pass repo_id as a query param.
```

---

### v2-09

```
/create-spec v2-09: implement DELETE /services/{id} in backend/routers/services.py. The route requires both auth headers. Set RLS context first. Query SELECT id FROM services WHERE id = $1 AND user_id = $2 — return 404 if not found. Then DELETE FROM services WHERE id = $1 (RLS also enforces this). The cascade defined on endpoints and consumer_edges handles cleanup automatically. Return {status: "deleted"}. Add deleteService(serviceId) to lib/api.js if not already there — it sends DELETE to /services/{serviceId} with both auth headers.
```

---

### v2-10 (new — template literal and f-string URL detection)

```
/create-spec v2-10: extend extract_js_http_calls and extract_http_calls in backend/analysis/code_parser.py to also detect HTTP calls made through template literals (JS) and f-strings (Python), not just plain string literals. For JS: add a second tree-sitter query matching template_string as the URL argument to fetch() and axios.*(); walk the template_string node's children to collect the literal string segments and the positions of template_substitution nodes; reconstruct the URL pattern by joining the literal parts with {param} placeholders where substitutions were; extract the path portion (the segment starting with /) and return it. For Python: remove the _is_fstring skip in extract_http_calls; instead, when the url node is an f_string, walk its children to collect literal and interpolation segments; reconstruct the path pattern the same way. Both functions continue to return the same types as before (list[str] for JS, list[dict] with "url" key for Python) — the caller pipeline is unchanged. Add test cases: fetch with env var host and static path, fetch with dynamic path segment, axios.get with template literal, requests.get with f-string host, requests.get with f-string path segment.
```

---

### v2-11 (new — endpoint-level graph nodes with function names)

```
/create-spec v2-11: redesign the graph so each node is a specific endpoint function or caller function, not a service blob. Three levels of nesting: service group → file group → leaf node.

DB migration — four new columns:
  ALTER TABLE endpoints ADD COLUMN file_path VARCHAR(500);
  ALTER TABLE endpoints ADD COLUMN function_name VARCHAR(255);
  ALTER TABLE consumer_edges ADD COLUMN caller_file_path VARCHAR(500);
  ALTER TABLE consumer_edges ADD COLUMN caller_function_name VARCHAR(255);

code_parser.py changes:
  extract_route_decorators: extend the DECORATOR_QUERY to also capture the function_definition name node beneath the decorator; add "function_name" key to returned dicts.
  extract_js_routes: for Express routes, capture the handler name if it is a named identifier (second arg); for Next.js routes, use the exported function name as function_name. Add "function_name" key to returned dicts.
  extract_http_calls (Python): after matching the call node, walk .parent links up the AST to find the nearest function_definition ancestor; include its name as "caller_function_name" in returned dicts.
  extract_js_http_calls (JS/TS): same parent-walk to find enclosing function_declaration, method_definition, or named arrow function; change return type from list[str] to list[dict] with keys {url, file_path, caller_function_name}. Update analyze.py and all tests that call extract_js_http_calls.

analyze.py: pass file_path (relative to folder_path) and function_name when inserting endpoints; pass caller_file_path and caller_function_name when inserting consumer_edges. Update upsert SQL to include the new columns.

GET /graph in graph.py: return two types of leaf nodes:
  Provider endpoint node: id="ep:{endpoint_id}", label="{function_name}\n{METHOD} {path}", metadata: {file_path, service_name, service_id, node_type:"endpoint"}.
  Caller function node: id="caller:{caller_service_id}:{caller_file_path}:{caller_function_name}", label="{caller_function_name}", metadata: {caller_file_path, service_name, service_id, node_type:"caller"}.
  Edges: source=caller node id, target=provider endpoint node id.
  Both node types carry service_name and file_path so the frontend can build the 3-level hierarchy without extra requests.

DependencyGraph.jsx: build three React Flow node levels using the parentId field:
  Service group nodes (type="group"): id="{service_name}", no parent.
  File group nodes (type="group"): id="{service_name}:{file_path}", parentId="{service_name}".
  Leaf nodes: parentId="{service_name}:{file_path}".
  Auto-layout service groups with dagre (services that only call at top, only expose at bottom, both in middle). Within each file group, stack leaf nodes vertically. Group boxes auto-size to fit children.

ImpactPanel.jsx: when an endpoint node is clicked, show consumers as "{caller_function_name} in {caller_file_path} ({service_name})" with call_count and last_seen_at.
```
