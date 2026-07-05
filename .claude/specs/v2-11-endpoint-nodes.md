# Spec v2-11 — Endpoint-Level Graph Nodes

## Goal
Replace the current two-level (service, endpoint) graph shape with function-level leaf nodes — provider endpoint handlers and caller functions — nested three levels deep in the UI (service group → file group → leaf node), so clicking `GET /users/{id}` shows exactly which functions in which files call it, not just which services.

## Depends on
- v2-01 (db migration pattern — this spec adds its own migration the same way)
- v2-02 (backend auth — `get_github_token`, `get_current_user_id`, `set_rls_context`)
- v2-03 (upsert — this spec directly modifies the endpoint upsert SQL and `UPSERT_EDGE_SQL` that v2-03 established)
- v2-05 (JS/TS parser — `extract_js_routes`, `extract_js_http_calls` already exist)
- v2-08 (scoped graph — `GET /graph?repo_id=...`, `GraphPageInner.jsx` mount-driven fetch)
- v2-10 (template literals — `extract_http_calls`/`extract_js_http_calls` already reconstruct f-string/template URLs; this spec's AST-walking helpers follow the same "walk `.parent` links" style introduced there)

## Context
CLAUDE.md's "Endpoint-level graph nodes" key decision and its `endpoints`/`consumer_edges` schema (`file_path`, `function_name`, `caller_file_path`, `caller_function_name` columns) and its `GraphNode`/`GraphEdge`/`EndpointOut`/`ConsumerOut` Pydantic models already describe the target end state exactly — this spec is what makes the *current* code match them.

Today:
- `endpoints` and `consumer_edges` have no `file_path`/`function_name`/`caller_file_path`/`caller_function_name` columns.
- `code_parser.py`'s four extractor functions return only `{method, path[, spec_source]}` for routes and `{url}` (Python) / plain `url` strings (JS) for calls — no file or function context.
- `graph.py` runs three separate queries (services, endpoints-with-edges, edges) and returns flat `GraphNode{id, name}` / `GraphEdge{source, target, endpoint_path, endpoint_method, call_count, last_seen_at}` — one node per *service*, one node per *endpoint*, no per-file or per-function granularity.
- `DependencyGraph.jsx` renders whatever nodes/edges it's handed with no grouping; `GraphPageInner.jsx` does the raw→React-Flow-node transformation itself.
- `ImpactPanel.jsx` shows only `service_name`, `call_count`, `last_seen_at`, `source` per consumer — no caller function or file.

After this spec: a service with `routers/users.py` exposing `get_user`, `list_users`, `update_user` renders as three separate leaf nodes inside one file-group box inside one service-group box, each with its own inbound edges from the specific caller functions that call it.

**Known limitation, inherited from the schema, not introduced by this spec:** `consumer_edges` keeps its `UNIQUE(caller_service_id, endpoint_id)` constraint unchanged (per CLAUDE.md — not relitigated here). That means only *one* row can exist per (caller service, endpoint) pair, not one per (caller service, caller file, caller function, endpoint). If two different functions in two different files of the *same* caller service both call the *same* downstream endpoint, `ON CONFLICT ... DO UPDATE` overwrites the first function's `caller_file_path`/`caller_function_name` with the second's the next time that service is analyzed — only the most-recently-processed caller function survives per (caller service, endpoint) pair. In practice this means "shows exactly which functions call it" is accurate per distinct *calling service*, not per distinct calling *function* when a service calls the same endpoint from more than one place. This is expected behavior given the locked schema, not a bug to fix in this spec.

## Files to create
None.

## Files to edit

Backend:
- `backend/analysis/code_parser.py` — capture `function_name` in route extractors; capture `caller_function_name` (and, for JS, `file_path`) in call extractors via AST parent-walking.
- `backend/routers/analyze.py` — compute and pass `file_path`/`function_name` on endpoint inserts, `caller_file_path`/`caller_function_name` on edge inserts; update both upsert SQL statements.
- `backend/routers/graph.py` — single joined query per CLAUDE.md's canonical graph SQL; build endpoint + caller leaf `GraphNode`s and `GraphEdge`s.
- `backend/routers/endpoints.py` — `GET /endpoints` returns `file_path`/`function_name`; impact-analysis returns `caller_file_path`/`caller_function_name`.
- `backend/models.py` — `GraphNode`, `GraphEdge`, `EndpointOut`, `ConsumerOut` updated to match CLAUDE.md's Pydantic models section exactly.
- `backend/tests/test_code_parser.py` — update every existing exact-dict assertion to include the new keys; add new test cases (listed below).
- `backend/tests/test_routes.py` — update analyze/graph/endpoints test blocks for the new columns and the new single-query graph shape.

Frontend:
- `frontend/components/DependencyGraph.jsx` — takes raw `GraphNode[]`/`GraphEdge[]` (API shape, not pre-transformed) and builds the 3-level React Flow hierarchy internally, auto-laid-out with dagre.
- `frontend/components/ImpactPanel.jsx` — replace the `endpointLabel` prop (parsed into method/path) with explicit `method`, `path`, `functionName` props; render each consumer row as `"{caller_function_name} in {caller_file_path} ({service_name})"`.
- `frontend/app/graph/GraphPageInner.jsx` — stop building React Flow nodes itself; pass filtered raw API nodes/edges straight to `DependencyGraph`; update `handleNodeClick` for the new `ep:`/`caller:` id scheme and new `ImpactPanel` props.
- `frontend/lib/graphFilter.js` — filter on `node.label` (present directly on the API `GraphNode`) instead of `node.data.label`; match the `ep:` id prefix instead of `endpoint-`.
- `frontend/__tests__/DependencyGraph.test.jsx` — rewrite for the new raw-node-in, grouped-node-out contract.
- `frontend/__tests__/ImpactPanel.test.jsx` — this file is already stale relative to the current component (asserts `"No consumers found."` and `"Failed to load consumers. Please try again."` against a component that renders `"No consumers found"` and `"Failed to load consumers."` — 4 of its 8 tests already fail before this spec). Rewrite it to match the real component's text and the new `method`/`path`/`functionName` props, folding in coverage for the new consumer-row format; do not leave it in its currently-broken state.
- `frontend/__tests__/GraphPageInner_independent.test.jsx` and `frontend/__tests__/ImpactPanel_spec10.test.jsx` — update the mocked `fetchGraph`/`DependencyGraph` fixtures to the new node id scheme (`ep:{id}` / `caller:{...}`) and new `GraphNode` shape (`label`, `node_type`, `method`, `path`, `function_name`, `file_path`, `service_name`, `service_id` instead of `{id, name}`); update `ImpactPanel` prop assertions (`endpointLabel` → `method`/`path`/`functionName`).

Config:
- `frontend/package.json` — add `@dagrejs/dagre` as a dependency; run `npm install @dagrejs/dagre` so `package-lock.json` picks it up. Note: CLAUDE.md's Tech Stack table does not yet list `@dagrejs/dagre` (it isn't on the "not in the stack" forbidden list either — it's simply new); once this spec ships, CLAUDE.md's Tech Stack table should be updated separately to add it, so the "exact stack" documentation stays accurate for future spec-writing sessions.

## Implementation details

### 1. Database migration

Run via the Supabase MCP `apply_migration` tool, migration name `v2_11_endpoint_nodes`. Idempotent, following the `v2-01` pattern:

```sql
ALTER TABLE public.endpoints
  ADD COLUMN IF NOT EXISTS file_path VARCHAR(500),
  ADD COLUMN IF NOT EXISTS function_name VARCHAR(255);

ALTER TABLE public.consumer_edges
  ADD COLUMN IF NOT EXISTS caller_file_path VARCHAR(500),
  ADD COLUMN IF NOT EXISTS caller_function_name VARCHAR(255);
```

All four columns are nullable — existing rows (and `spec_source='openapi'` rows going forward, see below) have no value for them, and CLAUDE.md's schema does not mark them `NOT NULL`.

Manual verification (same style as v2-01):
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'endpoints'
  AND column_name IN ('file_path', 'function_name');

SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'consumer_edges'
  AND column_name IN ('caller_file_path', 'caller_function_name');
```
Expected: two rows each.

### 2. `backend/analysis/code_parser.py`

#### New helpers (module-level)

```python
def _enclosing_py_function_name(node) -> str | None:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            name_node = current.child_by_field_name("name")
            return name_node.text.decode("utf-8") if name_node is not None else None
        current = current.parent
    return None


def _enclosing_js_function_name(node) -> str | None:
    current = node.parent
    while current is not None:
        if current.type in ("function_declaration", "method_definition"):
            name_node = current.child_by_field_name("name")
            return name_node.text.decode("utf-8") if name_node is not None else None
        if current.type == "arrow_function":
            parent = current.parent
            if parent is not None and parent.type == "variable_declarator":
                name_node = parent.child_by_field_name("name")
                if name_node is not None:
                    return name_node.text.decode("utf-8")
        current = current.parent
    return None
```

`_enclosing_py_function_name` walks `.parent` links exactly like `_reconstruct_fstring`'s sibling `_extract_path_from_pattern` walks bytes — stop at the first ancestor `function_definition` and read its `name` field. Returns `None` for calls made at module scope (no enclosing function).

`_enclosing_js_function_name` additionally handles the "named arrow function" case (`const fetchUser = () => {...}`): an `arrow_function` node has no name of its own, so when the walk reaches one, check whether its immediate parent is a `variable_declarator` and use that declarator's `name` field. An anonymous arrow function passed inline (e.g. `setTimeout(() => fetch(...), 100)`) has no such parent and the walk continues upward looking for an outer named function; if none exists, returns `None`.

#### `DECORATOR_QUERY` — capture the function name

```python
DECORATOR_QUERY = PY_LANGUAGE.query("""
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier)
        attribute: (identifier) @method)
      arguments: (argument_list
        (string) @path)))
  definition: (function_definition
    name: (identifier) @function_name))
""")
```

`decorated_definition` in the pinned `tree-sitter-python` grammar has a `definition` field pointing at the wrapped `function_definition` (or `class_definition`) — adding `definition: (function_definition name: (identifier) @function_name)` alongside the existing decorator pattern captures the handler's name in the same match, with no change to how `@method`/`@path` are captured.

#### `extract_route_decorators(file_path: str) -> list[dict]`

```python
for _, match in DECORATOR_QUERY.matches(tree.root_node):
    method_node = match.get("method")
    path_node = match.get("path")
    function_name_node = match.get("function_name")
    if method_node is None or path_node is None:
        continue
    method_text = method_node.text.decode("utf-8").upper()
    if method_text not in {"GET", "POST", "PUT", "DELETE"}:
        continue
    if _is_fstring(path_node):
        continue
    path_value = _node_string_value(path_node)
    if path_value is None:
        continue
    function_name = function_name_node.text.decode("utf-8") if function_name_node is not None else None
    results.append({"method": method_text, "path": path_value, "function_name": function_name})
```
Only the final `results.append(...)` line changes — one new key, `function_name`. Return type is still `list[dict]`.

#### `extract_http_calls(file_path: str) -> list[dict]`

Add `"caller_function_name": _enclosing_py_function_name(url_node)` to both `results.append(...)` call sites (the f-string-reconstruction branch and the plain-string branch):

```python
if _is_fstring(url_node):
    pattern = _reconstruct_fstring(url_node)
    path = _extract_path_from_pattern(pattern)
    if path is None:
        continue
    results.append({"url": path, "caller_function_name": _enclosing_py_function_name(url_node)})
    continue
url_value = _node_string_value(url_node)
if url_value is None:
    continue
results.append({"url": url_value, "caller_function_name": _enclosing_py_function_name(url_node)})
```
Return type is still `list[dict]` — one new key, `caller_function_name` (`str | None`). `file_path` is **not** added here (the Python side of `analyze.py` already has the absolute file path from its own `glob.glob` loop variable and computes the relative path itself — no need to round-trip it through the extractor, unlike the JS side below).

#### `extract_js_routes(file_path: str) -> list[dict]`

Express case — capture the handler name if the argument immediately after the path string is a bare identifier (not a query change; read the AST directly, since query patterns can't cleanly express "optional adjacent sibling" without risking spurious matches on later identifiers in a longer middleware chain):

```python
for _, match in express_query.matches(tree.root_node):
    method_node = match.get("method")
    path_node = match.get("path")
    if method_node is None or path_node is None:
        continue
    method = method_node.text.decode("utf-8").upper()
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        continue
    raw = path_node.text.decode("utf-8")
    if raw.startswith("`"):
        continue
    try:
        path_value = ast.literal_eval(raw)
    except Exception:
        continue
    if not isinstance(path_value, str):
        continue
    function_name = None
    next_named_sibling = path_node.next_named_sibling
    if next_named_sibling is not None and next_named_sibling.type == "identifier":
        function_name = next_named_sibling.text.decode("utf-8")
    results.append({
        "method": method, "path": path_value,
        "spec_source": "decorator_js", "function_name": function_name,
    })
```
Use `path_node.next_named_sibling`, **not** `path_node.next_sibling` — verified against the pinned `tree-sitter-javascript` grammar that the `arguments` node's raw children (via `.next_sibling`) go `string, ",", identifier, ")"`, i.e. the *unnamed* comma token sits directly between the path string and the handler. `.next_sibling` would therefore always land on the comma (`type == ","`), never on the identifier, silently producing `function_name = None` in every case. `.next_named_sibling` skips anonymous/punctuation nodes and correctly returns the argument-list child immediately following the path string — the second positional argument. For `app.get('/users', handler)` this is the `identifier` node `handler`. For `app.get('/users', mw, handler)` the second argument is `mw` (also an identifier) — this spec intentionally captures whichever identifier is *second*, matching the literal "second arg" rule; multi-middleware handler resolution is not in scope. For `app.get('/users', (req, res) => {...})` the next named sibling is an `arrow_function`, not an `identifier`, so `function_name` stays `None`.

Next.js case — the exported function name doubles as `function_name` (it's already `GET`/`POST`/etc., matching CLAUDE.md's example `function_name` value for Next.js routes):

```python
for _, match in fn_query.matches(tree.root_node):
    name_node = match.get("name")
    if name_node is None:
        continue
    name_text = name_node.text.decode("utf-8")
    if name_text in {"GET", "POST", "PUT", "DELETE"}:
        results.append({
            "method": name_text, "path": api_path,
            "spec_source": "nextjs_route", "function_name": name_text,
        })
```

#### `extract_js_http_calls(file_path: str) -> list[dict]`

Return type changes from `list[str]` to `list[dict]` with keys `{url, file_path, caller_function_name}`. Update `_collect_js_calls` to build dicts and take `file_path` as a parameter:

```python
def _collect_js_calls(query, tree_root, is_valid_call, resolve_url, file_path) -> list[dict]:
    out = []
    for _, match in query.matches(tree_root):
        url_node = match.get("url")
        if url_node is None or not is_valid_call(match):
            continue
        url = resolve_url(url_node)
        if url is not None:
            out.append({
                "url": url,
                "file_path": file_path,
                "caller_function_name": _enclosing_js_function_name(url_node),
            })
    return out


def extract_js_http_calls(file_path: str) -> list[dict]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        root = tree.root_node
        results = []

        results += _collect_js_calls(fetch_query, root, _is_fetch_call, _resolve_plain_string_url, file_path)
        results += _collect_js_calls(axios_query, root, _is_axios_call, _resolve_plain_string_url, file_path)
        results += _collect_js_calls(
            fetch_template_query, root, _is_fetch_call,
            lambda url_node: _resolve_template_url(url_node, source), file_path,
        )
        results += _collect_js_calls(
            axios_template_query, root, _is_axios_call,
            lambda url_node: _resolve_template_url(url_node, source), file_path,
        )
        return results
    except Exception:
        return []
```
The four query definitions themselves (`fetch_query`, `axios_query`, `fetch_template_query`, `axios_template_query`) and `_is_fetch_call`/`_is_axios_call`/`_resolve_plain_string_url`/`_resolve_template_url` are unchanged — only the call sites now pass `file_path` through and `_collect_js_calls` returns dicts instead of bare URL strings.

`file_path` in each returned dict is exactly the `file_path` argument passed into `extract_js_http_calls` (the same absolute path `analyze.py`'s glob loop already has) — this is deliberately redundant with what the caller already knows, kept for parity with how `extract_js_routes` is self-contained, and so callers of `extract_js_http_calls` never need a second parameter threaded through just to label results.

### 3. `backend/routers/analyze.py`

#### Endpoint discovery — add `file_path`/`function_name` to `discovered` dicts

```python
if result is not None:
    discovered = [
        {**ep, "file_path": None, "function_name": None}
        for ep in result["endpoints"]
    ]
else:
    discovered = []
    for py_file in glob.glob(os.path.join(folder_path, "**", "*.py"), recursive=True):
        if not _safe_path(py_file, tmp_dir):
            continue
        if _is_in_ignored_dir(py_file, folder_path):
            continue
        rel_path = os.path.relpath(py_file, folder_path).replace(os.sep, "/")
        for ep in extract_route_decorators(py_file):
            discovered.append({
                "method": ep["method"],
                "path": ep["path"],
                "spec_source": "decorator",
                "file_path": rel_path,
                "function_name": ep.get("function_name"),
            })
    for pattern in ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"):
        for js_file in glob.glob(os.path.join(folder_path, pattern), recursive=True):
            if not _safe_path(js_file, tmp_dir):
                continue
            if _is_in_ignored_dir(js_file, folder_path):
                continue
            rel_path = os.path.relpath(js_file, folder_path).replace(os.sep, "/")
            for ep in extract_js_routes(js_file):
                ep["file_path"] = rel_path
                discovered.append(ep)
```
OpenAPI-sourced endpoints (`parse_service` / `spec_parser.py`) get `file_path=None, function_name=None` — `spec_parser.py` is out of scope for this spec (CLAUDE.md does not require it to track file/function context, and OpenAPI specs have no notion of "enclosing function"). The frontend's file-group layout treats a `None` `file_path` as its own `"(unknown)"` bucket (see DependencyGraph.jsx below).

#### Endpoint upsert — new columns, `DO UPDATE` always returns a row

```python
ep_row = await conn.fetchrow(
    """INSERT INTO endpoints (service_id, method, path, spec_source, file_path, function_name)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (service_id, method, path)
       DO UPDATE SET file_path = EXCLUDED.file_path, function_name = EXCLUDED.function_name
       RETURNING id""",
    service_id, endpoint["method"], endpoint["path"], endpoint["spec_source"],
    endpoint.get("file_path"), endpoint.get("function_name"),
)
endpoints_count += 1
```
The previous `ON CONFLICT ... DO NOTHING` + fallback `SELECT id FROM endpoints WHERE ...` block is **removed entirely** — `DO UPDATE` always returns a row via `RETURNING id`, so the fallback branch (`if ep_row is None: ep_row = await conn.fetchrow(...)`) no longer has a code path that triggers it and is dead code. This matches CLAUDE.md's canonical upsert SQL in the "Core SQL queries" section.

#### `UPSERT_EDGE_SQL` — new columns

```python
UPSERT_EDGE_SQL = """INSERT INTO consumer_edges
    (caller_service_id, endpoint_id, last_seen_at, call_count, source, caller_file_path, caller_function_name)
VALUES ($1, $2, NOW(), 1, $3, $4, $5)
ON CONFLICT (caller_service_id, endpoint_id)
DO UPDATE SET last_seen_at = NOW(), source = EXCLUDED.source,
              caller_file_path = EXCLUDED.caller_file_path,
              caller_function_name = EXCLUDED.caller_function_name"""
```
(Matches CLAUDE.md's canonical edge upsert SQL exactly.)

#### Consumer-edge insertion — pass the two new params

Python side (`extract_http_calls` doesn't carry `file_path`, so compute it the same way the endpoint-discovery loop does, from the `py_file` loop variable already in scope):

```python
for call in extract_http_calls(py_file):
    url_path = _extract_path(call["url"])
    if not url_path:
        continue
    matched_path = match_url_to_endpoint(url_path, known_paths)
    if matched_path is None:
        continue
    matched_endpoint = next((e for e in known_endpoints if e["path"] == matched_path), None)
    if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
        continue
    caller_rel_path = os.path.relpath(py_file, folder_path).replace(os.sep, "/")
    await conn.execute(
        UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static",
        caller_rel_path, call.get("caller_function_name"),
    )
    edges_count += 1
```

JS side (`extract_js_http_calls` now returns dicts carrying `file_path` and `caller_function_name`; note the comment `# JS/TS HTTP calls (extract_js_http_calls returns list[str], not list[dict])` above this loop is now stale and must be removed/updated):

```python
for call in extract_js_http_calls(js_file):
    url_path = _extract_path(call["url"])
    if not url_path:
        continue
    matched_path = match_url_to_endpoint(url_path, known_paths)
    if matched_path is None:
        continue
    matched_endpoint = next((e for e in known_endpoints if e["path"] == matched_path), None)
    if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
        continue
    caller_rel_path = os.path.relpath(call["file_path"], folder_path).replace(os.sep, "/")
    await conn.execute(
        UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static",
        caller_rel_path, call.get("caller_function_name"),
    )
    edges_count += 1
```

### 4. `backend/models.py`

Replace the current `GraphNode`/`GraphEdge`/`EndpointOut`/`ConsumerOut` with CLAUDE.md's exact definitions (copied verbatim from the "Pydantic models" section):

```python
class EndpointOut(BaseModel):
    id: int
    service_id: int
    method: str
    path: str
    spec_source: Optional[str]
    file_path: Optional[str]
    function_name: Optional[str]


class ConsumerOut(BaseModel):
    service_name: str
    caller_function_name: Optional[str]
    caller_file_path: Optional[str]
    call_count: int
    last_seen_at: datetime
    source: str


class GraphNode(BaseModel):
    id: str
    node_type: str
    label: str
    function_name: Optional[str]
    method: Optional[str]
    path: Optional[str]
    file_path: Optional[str]
    service_name: str
    service_id: int


class GraphEdge(BaseModel):
    source: str
    target: str
    call_count: int
    last_seen_at: datetime
```
`GraphOut` is unchanged (`nodes: list[GraphNode]`, `edges: list[GraphEdge]`). `endpoint_path`/`endpoint_method` are removed from `GraphEdge` — that information now lives on the endpoint `GraphNode` itself (`method`, `path`).

### 5. `backend/routers/graph.py`

Replace the three-query implementation with CLAUDE.md's single canonical joined query, then build deduplicated endpoint/caller nodes plus one edge per row:

```python
from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()

GRAPH_QUERY = """
SELECT
  e.id               AS endpoint_id,
  e.service_id       AS endpoint_service_id,
  es.name            AS endpoint_service_name,
  e.file_path        AS endpoint_file_path,
  e.function_name    AS endpoint_function_name,
  e.method, e.path,
  ce.caller_service_id,
  cs.name            AS caller_service_name,
  ce.caller_file_path,
  ce.caller_function_name,
  ce.call_count, ce.last_seen_at
FROM consumer_edges ce
JOIN services cs ON cs.id = ce.caller_service_id
JOIN endpoints e  ON e.id  = ce.endpoint_id
JOIN services es  ON es.id = e.service_id
WHERE cs.repo_id = $1
"""


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
            rows = await conn.fetch(GRAPH_QUERY, repo_id)

    endpoint_nodes: dict[str, GraphNode] = {}
    caller_nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for r in rows:
        ep_id = f"ep:{r['endpoint_id']}"
        if ep_id not in endpoint_nodes:
            function_name = r["endpoint_function_name"]
            label = f"{function_name}\n{r['method']} {r['path']}" if function_name else f"{r['method']} {r['path']}"
            endpoint_nodes[ep_id] = GraphNode(
                id=ep_id,
                node_type="endpoint",
                label=label,
                function_name=function_name,
                method=r["method"],
                path=r["path"],
                file_path=r["endpoint_file_path"],
                service_name=r["endpoint_service_name"],
                service_id=r["endpoint_service_id"],
            )

        caller_function_name = r["caller_function_name"]
        caller_id = f"caller:{r['caller_service_id']}:{r['caller_file_path']}:{caller_function_name}"
        if caller_id not in caller_nodes:
            caller_nodes[caller_id] = GraphNode(
                id=caller_id,
                node_type="caller",
                label=caller_function_name or "unknown",
                function_name=caller_function_name,
                method=None,
                path=None,
                file_path=r["caller_file_path"],
                service_name=r["caller_service_name"],
                service_id=r["caller_service_id"],
            )

        edges.append(GraphEdge(
            source=caller_id,
            target=ep_id,
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
        ))

    return GraphOut(
        nodes=list(endpoint_nodes.values()) + list(caller_nodes.values()),
        edges=edges,
    )
```

Notes:
- `repo_id: str` is still a required query param (unchanged from v2-08 — no default, so a missing `?repo_id=` still 422s).
- Only **one** `conn.fetch` call now, not three — a caller-service that neither exposes nor is exposed doesn't appear at all (identical to today: a service with zero consumer edges never appeared in the old edge-derived endpoint list either; the old service-level node list did include such services, but per CLAUDE.md's "Endpoint-level graph nodes" decision, service identity now only exists implicitly via `service_name`/`service_id` on leaf nodes, built into groups on the frontend — a service that neither calls nor is called has no leaf nodes and correctly does not appear).
- Deduplication is required because one endpoint or one caller function can appear in multiple `consumer_edges` rows (multiple callers of the same endpoint, or one caller function calling multiple endpoints) — without the `endpoint_nodes`/`caller_nodes` dicts keyed by id, the same node would be emitted once per edge.
- `caller_id` embeds `caller_file_path`/`caller_function_name` directly (both can legitimately be `NULL` in the DB — e.g. rows written before this migration, or a call made at module scope with no enclosing function); Postgres returns `None` for those, and `f"...{None}"` renders as the literal string `"None"` in the id — this is acceptable (ids just need to be stable and unique, not pretty) but the **label** falls back to `"unknown"` so nothing renders as the string "None" in the UI.

### 6. `backend/routers/endpoints.py`

`GET /endpoints` — select and return the two new columns:
```python
rows = await conn.fetch(
    "SELECT id, service_id, method, path, spec_source, file_path, function_name"
    " FROM endpoints WHERE service_id = $1 ORDER BY id",
    service_id,
)
...
EndpointOut(
    id=r["id"], service_id=r["service_id"], method=r["method"], path=r["path"],
    spec_source=r["spec_source"], file_path=r["file_path"], function_name=r["function_name"],
)
```
(Same change to the no-`service_id` branch's `SELECT`.)

`GET /endpoints/{id}/impact-analysis` — CLAUDE.md's canonical query, adding `caller_function_name`/`caller_file_path`:
```python
rows = await conn.fetch(
    "SELECT s.name AS service_name, ce.caller_function_name, ce.caller_file_path,"
    " ce.call_count, ce.last_seen_at, ce.source"
    " FROM consumer_edges ce"
    " JOIN services s ON s.id = ce.caller_service_id"
    " WHERE ce.endpoint_id = $1"
    " ORDER BY ce.call_count DESC",
    id,
)
...
ConsumerOut(
    service_name=r["service_name"],
    caller_function_name=r["caller_function_name"],
    caller_file_path=r["caller_file_path"],
    call_count=r["call_count"],
    last_seen_at=r["last_seen_at"],
    source=r["source"],
)
```

### 7. `frontend/components/DependencyGraph.jsx`

Takes the **raw** API shapes as props — `nodes: GraphNode[]` (fields: `id`, `node_type`, `label`, `function_name`, `method`, `path`, `file_path`, `service_name`, `service_id`) and `edges: GraphEdge[]` (fields: `source`, `target`, `call_count`, `last_seen_at`) — not pre-built React Flow elements. It builds the 3-level hierarchy and lays it out with dagre internally, then renders `<ReactFlow>`.

```jsx
'use client'
import { useMemo } from 'react'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'

const LEAF_WIDTH = 220
const LEAF_HEIGHT = 56
const LEAF_GAP = 10
const FILE_HEADER = 28
const FILE_PADDING = 16
const FILE_GAP = 20
const SERVICE_PADDING = 24
const SERVICE_HEADER = 32
const SERVICE_COL_GAP = 60
const TIER_ROW_GAP = 220

const SERVICE_GROUP_STYLE = {
  background: 'rgba(20, 33, 61, 0.35)',
  border: '1px solid #29447e',
  borderRadius: '10px',
}
const FILE_GROUP_STYLE = {
  background: 'rgba(12, 20, 37, 0.6)',
  border: '1px dashed #3e67bf',
  borderRadius: '6px',
}
const ENDPOINT_LEAF_STYLE = {
  background: '#0c1425', border: '1.5px solid #fca311', borderColor: '#fca311',
  color: '#e5e5e5', borderRadius: '6px', fontSize: '12px',
  fontFamily: 'ui-monospace, SFMono-Regular, monospace', padding: '8px 12px',
  whiteSpace: 'pre-line',
}
const CALLER_LEAF_STYLE = {
  background: '#14213d', border: '1px solid #29447e', borderColor: '#29447e',
  color: '#e5e5e5', borderRadius: '6px', fontSize: '12px',
  fontFamily: 'ui-monospace, SFMono-Regular, monospace', padding: '8px 12px',
}

const defaultEdgeOptions = {
  type: 'smoothstep',
  style: { stroke: '#29447e', strokeWidth: 1.5 },
  labelStyle: { fill: '#8a8a8a', fontSize: 10, fontFamily: 'ui-monospace, SFMono-Regular, monospace' },
  labelBgStyle: { fill: '#000000', fillOpacity: 0.85 },
  labelBgPadding: [5, 3],
}

function buildElements(nodes, edges) {
  const byService = new Map()
  for (const n of nodes) {
    if (!byService.has(n.service_name)) {
      byService.set(n.service_name, { serviceId: n.service_id, files: new Map() })
    }
    const svc = byService.get(n.service_name)
    const fileKey = n.file_path ?? '(unknown)'
    if (!svc.files.has(fileKey)) svc.files.set(fileKey, [])
    svc.files.get(fileKey).push(n)
  }

  const providerServices = new Set(nodes.filter((n) => n.node_type === 'endpoint').map((n) => n.service_name))
  const callerServices = new Set(nodes.filter((n) => n.node_type === 'caller').map((n) => n.service_name))
  function tierOf(serviceName) {
    const isProvider = providerServices.has(serviceName)
    const isCaller = callerServices.has(serviceName)
    if (isCaller && !isProvider) return 0
    if (isCaller && isProvider) return 1
    return 2
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]))
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: SERVICE_COL_GAP, ranksep: TIER_ROW_GAP })
  g.setDefaultEdgeLabel(() => ({}))
  for (const serviceName of byService.keys()) g.setNode(serviceName, { width: 1, height: 1 })
  const seenServiceEdges = new Set()
  for (const e of edges) {
    const caller = nodeById.get(e.source)
    const target = nodeById.get(e.target)
    if (!caller || !target || caller.service_name === target.service_name) continue
    const key = `${caller.service_name}->${target.service_name}`
    if (!seenServiceEdges.has(key)) {
      seenServiceEdges.add(key)
      g.setEdge(caller.service_name, target.service_name)
    }
  }
  dagre.layout(g)

  const tiers = [[], [], []]
  for (const serviceName of byService.keys()) tiers[tierOf(serviceName)].push(serviceName)
  for (const tier of tiers) tier.sort((a, b) => g.node(a).x - g.node(b).x)

  const rfNodes = []
  tiers.forEach((tierServices, tierIndex) => {
    let cursorX = 0
    const tierY = tierIndex * TIER_ROW_GAP
    for (const serviceName of tierServices) {
      const { files } = byService.get(serviceName)
      let fileCursorX = SERVICE_PADDING
      let serviceHeight = SERVICE_HEADER
      const fileLayouts = []
      for (const [filePath, leaves] of files) {
        const fileWidth = LEAF_WIDTH + FILE_PADDING * 2
        const fileHeight = FILE_HEADER + leaves.length * (LEAF_HEIGHT + LEAF_GAP) + FILE_PADDING
        fileLayouts.push({ filePath, leaves, x: fileCursorX, width: fileWidth, height: fileHeight })
        fileCursorX += fileWidth + FILE_GAP
        serviceHeight = Math.max(serviceHeight, SERVICE_HEADER + fileHeight + SERVICE_PADDING)
      }
      const serviceWidth = fileCursorX - FILE_GAP + SERVICE_PADDING

      rfNodes.push({
        id: serviceName, type: 'group',
        position: { x: cursorX, y: tierY },
        style: { width: serviceWidth, height: serviceHeight, ...SERVICE_GROUP_STYLE },
        data: { label: serviceName },
      })

      for (const fl of fileLayouts) {
        const fileGroupId = `${serviceName}:${fl.filePath}`
        rfNodes.push({
          id: fileGroupId, type: 'group', parentId: serviceName, extent: 'parent',
          position: { x: fl.x, y: SERVICE_HEADER },
          style: { width: fl.width, height: fl.height, ...FILE_GROUP_STYLE },
          data: { label: fl.filePath },
        })
        fl.leaves.forEach((leaf, i) => {
          rfNodes.push({
            id: leaf.id, parentId: fileGroupId, extent: 'parent',
            position: { x: FILE_PADDING, y: FILE_HEADER + i * (LEAF_HEIGHT + LEAF_GAP) },
            data: { label: leaf.label, ...leaf },
            style: leaf.node_type === 'endpoint' ? ENDPOINT_LEAF_STYLE : CALLER_LEAF_STYLE,
          })
        })
      }
      cursorX += serviceWidth + SERVICE_COL_GAP
    }
  })

  const rfEdges = edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    label: `×${e.call_count}`,
  }))

  return { rfNodes, rfEdges }
}

export default function DependencyGraph({ nodes, edges, onNodeClick }) {
  const { rfNodes, rfEdges } = useMemo(() => buildElements(nodes, edges), [nodes, edges])

  return (
    <div style={{ width: '100%', height: '100%', background: '#000000' }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodeClick={onNodeClick}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background color="#29447e" gap={28} size={1} variant="dots" />
        <Controls />
        <MiniMap
          nodeColor={(node) => (node.data?.node_type === 'endpoint' ? '#fca311' : '#29447e')}
          maskColor="rgba(0,0,0,0.7)"
        />
      </ReactFlow>
    </div>
  )
}
```

Key structural points (must hold regardless of exact pixel constants chosen at implementation time):
- Service group node: `id = service_name`, `type: 'group'`, no `parentId`.
- File group node: `id = "{service_name}:{file_path}"`, `type: 'group'`, `parentId = service_name`, `extent: 'parent'`.
- Leaf node: `id` is the API node's own `id` (`ep:{endpoint_id}` or `caller:{caller_service_id}:{caller_file_path}:{caller_function_name}`), `parentId = "{service_name}:{file_path}"`, `extent: 'parent'`, `data` includes the full original `GraphNode` (so `onNodeClick` handlers can read `node.data.node_type`, `node.data.method`, `node.data.path`, `node.data.function_name`, `node.data.file_path` directly off the clicked node).
- A `null` `file_path` (OpenAPI-sourced endpoints, or edges written before this migration) buckets into a literal `"(unknown)"` file group rather than crashing on a `Map` key of `null`.
- Tiering: a service that only ever appears as a caller (never owns an endpoint node) → top row; a service that only ever appears as an endpoint owner (never calls anything) → bottom row; a service that does both → middle row. Horizontal ordering within each row comes from a dagre layout pass over a small service-level graph (one dagre node per service, one dagre edge per distinct caller-service→endpoint-service pair) — dagre's assigned `x` is used purely to order services left-to-right per row to reduce edge crossings; its `y` is discarded in favor of the fixed tier.
- Each service/file group's `style.width`/`style.height` is computed from its children's count and size (leaf nodes stacked vertically within a file group; file groups placed left-to-right within a service group) — React Flow v12 does not auto-size `type: 'group'` nodes, so this must be computed explicitly.

### 8. `frontend/lib/graphFilter.js`

```javascript
export function filterGraph(nodes, edges, query) {
  const q = query.trim().toLowerCase()
  if (!q) return { visibleNodes: nodes, visibleEdges: edges }

  const visibleNodes = nodes.filter((node) => {
    if (node.node_type !== 'endpoint') return true
    return node.label.toLowerCase().includes(q)
  })

  const visibleNodeIds = new Set(visibleNodes.map((n) => n.id))
  const visibleEdges = edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
  )

  return { visibleNodes, visibleEdges }
}
```
Operates on raw API `GraphNode[]`/`GraphEdge[]` (called from `GraphPageInner.jsx` *before* handing filtered results to `DependencyGraph`, which does its own raw→React-Flow transformation) — only the id-scheme check (`node.node_type !== 'endpoint'` instead of `!node.id.startsWith('endpoint-')`) and the label source (`node.label` instead of `node.data.label`) change; caller nodes remain always-visible exactly as service nodes were always-visible before.

### 9. `frontend/app/graph/GraphPageInner.jsx`

Simplifies significantly — no more manual React-Flow-node construction, no more `SERVICE_NODE_STYLE`/`ENDPOINT_NODE_STYLE` constants (those move into `DependencyGraph.jsx`):

```jsx
async function loadGraph() {
  setGraphLoading(true)
  try {
    const graphData = await fetchGraph(repoId)
    if (cancelled) return
    setNodes(graphData.nodes)
    setEdges(graphData.edges)
  } catch (err) {
    if (!cancelled) setGraphError(err.message)
  } finally {
    if (!cancelled) setGraphLoading(false)
  }
}
```
`nodes`/`edges` state now holds the raw API `GraphNode[]`/`GraphEdge[]` directly. `filterGraph(nodes, edges, search)` (unchanged call site) now filters those raw arrays. `<DependencyGraph nodes={visibleNodes} edges={visibleEdges} onNodeClick={handleNodeClick} />` is passed the raw filtered arrays — `DependencyGraph` does its own transformation internally (§7).

`handleNodeClick` and the `ImpactPanel` wiring change for the new id scheme and new `GraphNode` shape:

```jsx
function handleNodeClick(event, node) {
  if (node.data.node_type !== 'endpoint') return
  const endpointId = parseInt(node.id.replace('ep:', ''), 10)
  setSelectedEndpoint({
    id: endpointId,
    functionName: node.data.function_name,
    method: node.data.method,
    path: node.data.path,
  })
}
```
```jsx
{selectedEndpoint && (
  <ImpactPanel
    endpointId={selectedEndpoint.id}
    functionName={selectedEndpoint.functionName}
    method={selectedEndpoint.method}
    path={selectedEndpoint.path}
    onClose={() => setSelectedEndpoint(null)}
  />
)}
```
`EmptyState`'s `hasRepo` check still uses `Boolean(repoId)`, and the "no graph loaded" condition still checks `nodes.length === 0` (now checking the raw API node count, which is still zero exactly when the repo has no consumer edges — a repo with tracked services but zero discovered calls between them still renders `EmptyState`, matching today's behavior since the old endpoint-node query was also edge-driven).

### 10. `frontend/components/ImpactPanel.jsx`

Replace the `endpointLabel` prop + `parseLabel` helper with explicit `method`, `path`, `functionName` props:

```jsx
export default function ImpactPanel({ endpointId, method, path, functionName, onClose }) {
  ...
```
Header rendering: keep the existing method-badge + path layout (using `method`/`path` props directly instead of the output of `parseLabel(endpointLabel)`), and show `functionName` above/alongside it, e.g.:
```jsx
{functionName && (
  <p className="font-mono text-xs text-alabaster-300 truncate">{functionName}</p>
)}
<div className="flex items-center gap-2 flex-wrap">
  {method && (<span ...>{method}</span>)}
  <span className="font-mono text-sm text-alabaster truncate">{path}</span>
</div>
```
Remove the `parseLabel` function entirely — it's no longer used anywhere.

Consumer row — per this spec's args, render as `"{caller_function_name} in {caller_file_path} ({service_name})"`:
```jsx
<span className="text-sm font-medium text-white font-mono truncate">
  {c.caller_function_name ?? 'unknown'} in {c.caller_file_path ?? 'unknown file'} ({c.service_name})
</span>
```
replacing the current `<span ...>{c.service_name}</span>` line. `call_count`/`last_seen_at` bar and text rendering are unchanged.

## Test cases

### `backend/tests/test_code_parser.py`

Update every existing exact-dict-equality assertion to include the new key(s):
- All `extract_route_decorators(...)` assertions gain `"function_name": "<handler_name>"` (e.g. `test_extract_get_decorator` → `[{"method": "GET", "path": "/users/{id}", "function_name": "get_user"}]`).
- `test_extract_multiple_decorators` — each of the three dicts gains its own `function_name` (`get_user`, `create_order`, `delete_item`).
- `test_extract_non_string_path` and `test_extract_no_decorators` — still `[]`, unaffected.
- All `extract_http_calls(...)` assertions gain `"caller_function_name": None` where the call sites in the fixture source are at module scope (all current fixtures write calls at module scope with no enclosing `def`).
- All `extract_js_routes(...)` Express assertions gain `"function_name": None` unless the fixture already passes a bare identifier as the second arg (none currently do — all use inline handlers like `h`/`handler` as a *variable*, so check each fixture: `test_js_express_get` writes `app.get('/users', handler)` where `handler` is a declared `const handler = () => {}` — this **is** a bare identifier second argument, so its expected `function_name` is `"handler"`, not `None`; re-verify each Express fixture individually for whether its second argument is a bare identifier).
- All `extract_js_routes(...)` Next.js assertions gain `"function_name"` equal to the method itself (e.g. `{"method": "GET", "path": "/api/users", "spec_source": "nextjs_route", "function_name": "GET"}`).
- All `extract_js_http_calls(...)` assertions change from a list of strings to a list of dicts with `url`/`file_path`/`caller_function_name` keys, e.g. `test_js_fetch_call` → `extract_js_http_calls(str(f)) == [{"url": "http://user-service/users/1", "file_path": str(f), "caller_function_name": None}]`. Tests currently using `in result` (membership on a list of strings) must change to check membership of a dict, or extract just the `url` values first: `assert "http://svc/users/1" in [c["url"] for c in result]`.

New test cases:
- `test_extract_decorator_captures_function_name` — `@app.get("/users/{id}")\ndef get_user(id: int): ...` → `function_name == "get_user"`.
- `test_extract_decorator_async_function_name` — `@app.post("/orders")\nasync def create_order(): ...` → `function_name == "create_order"` (confirms `async def` still parses as a `function_definition`).
- `test_extract_http_call_captures_caller_function_name` — a `requests.get(...)` call inside `def sync_user(id):` → `caller_function_name == "sync_user"`.
- `test_extract_http_call_module_scope_no_caller_function_name` — a `requests.get(...)` call at module scope (no enclosing `def`) → `caller_function_name is None`.
- `test_extract_http_call_nested_function_caller_function_name` — a call inside a function nested inside another function → `caller_function_name` is the **innermost** enclosing function's name (walk stops at the first ancestor `function_definition`).
- `test_js_express_route_captures_handler_identifier` — `` function getUser(req, res) {}\napp.get('/users', getUser); `` → `function_name == "getUser"`.
- `test_js_express_route_arrow_handler_no_function_name` — `` app.get('/users', (req, res) => {}); `` → `function_name is None` (second arg is an `arrow_function`, not an `identifier`).
- `test_js_nextjs_route_function_name_equals_method` — existing Next.js fixture, assert `function_name == method` for each returned dict.
- `test_js_http_call_captures_caller_function_name_declaration` — `` function fetchUser() { fetch('http://svc/users/1'); } `` → `caller_function_name == "fetchUser"`.
- `test_js_http_call_captures_caller_function_name_named_arrow` — `` const fetchUser = () => { fetch('http://svc/users/1'); }; `` → `caller_function_name == "fetchUser"`.
- `test_js_http_call_captures_caller_function_name_method_definition` — a `class ApiClient { getUser() { fetch('http://svc/users/1'); } }` → `caller_function_name == "getUser"`.
- `test_js_http_call_anonymous_arrow_no_caller_function_name` — `` setTimeout(() => fetch('http://svc/users/1'), 100); `` (anonymous arrow with no enclosing named function) → `caller_function_name is None`.
- `test_js_http_call_module_scope_no_caller_function_name` — `fetch('http://svc/users/1');` at module scope → `caller_function_name is None`.
- `test_js_http_call_includes_file_path` — any existing `extract_js_http_calls` fixture, assert each returned dict's `"file_path"` equals `str(f)` (the path passed in).

### `backend/tests/test_routes.py`

Analyze route:
- `test_analyze_returns_ok_status`, `test_analyze_falls_back_to_decorators`, and other tests mocking `extract_route_decorators` with plain `{"method": ..., "path": ...}` dicts (no `function_name` key) must keep passing — `analyze.py` uses `ep.get("function_name")`, so a missing key must not raise `KeyError`. Add `test_analyze_endpoint_insert_includes_file_path_and_function_name` — mock `extract_route_decorators` to return `[{"method": "GET", "path": "/items", "function_name": "get_item"}]`, assert the endpoint upsert `fetchrow` call's positional args include the relative file path (position 5) and `"get_item"` (position 6).
- Rewrite `test_analyze_upsert_endpoint_idempotent` — the endpoint upsert SQL is now `ON CONFLICT ... DO UPDATE ... RETURNING id`, which always returns a row; remove the `None` / fallback-`SELECT` step from `conn.fetchrow`'s `side_effect` list (now: service upsert, endpoint upsert, service upsert, endpoint upsert — 4 entries instead of 5) and assert `"DO UPDATE"` (not `"DO NOTHING"`) appears in `endpoint_upsert_sql`.
- `test_analyze_consumer_edge_upserted`, `test_analyze_skips_fqdn_paths_that_dont_match`, `test_analyze_no_self_edges`, `test_analyze_upsert_edge_idempotent` — mocks of `extract_http_calls` returning `[{"url": "..."}]` (no `caller_function_name` key) must keep passing via `.get(...)`. Add `test_analyze_consumer_edge_includes_caller_context` — mock `extract_http_calls` to return `[{"url": "http://user-service/users/123", "caller_function_name": "sync_user"}]`, assert the `conn.execute` call for `consumer_edges` includes the relative caller file path and `"sync_user"` as its last two positional args.
- Add `test_analyze_js_consumer_edge_includes_caller_context` — same, but mocking `extract_js_http_calls` to return `[{"url": "http://user-service/users/123", "file_path": "<abs path>", "caller_function_name": "fetchUser"}]` inside a `.js` service folder, asserting the same.

`GET /graph` — rewrite for the single-query shape:
- `test_get_graph_returns_endpoint_and_caller_nodes` (replaces `test_get_graph_returns_nodes_and_edges`) — `conn.fetch` mocked with `return_value=[<one row with all GRAPH_QUERY columns>]` (not `side_effect=[...]` — only one query now), assert the response has one `node_type: "endpoint"` node with `id: "ep:5"` and one `node_type: "caller"` node with `id` starting `"caller:1:"`, and one edge with `source`/`target` matching those ids.
- `test_get_graph_empty_db` — `conn.fetch` returns `[]`; assert `nodes == []` and `edges == []`.
- `test_get_graph_requires_token` / `test_get_graph_requires_repo_id` — unchanged behavior (422s), still valid without touching query mocking.
- `test_get_graph_deduplicates_shared_endpoint_node` — two rows sharing the same `endpoint_id` but different `caller_service_id` (two different callers of the same endpoint) → response has exactly one node with that `ep:{id}`, and two edges targeting it.
- `test_get_graph_deduplicates_shared_caller_node` — two rows sharing the same `(caller_service_id, caller_file_path, caller_function_name)` but different `endpoint_id` (one caller function calling two different endpoints) → response has exactly one caller node, and two edges sourced from it.
- `test_get_graph_scopes_query_by_repo_id` — assert `conn.fetch` was called exactly once, with `repo_id` as its bind parameter.
- `test_get_graph_null_caller_function_name_labeled_unknown` — a row with `caller_function_name=None` → the caller node's `label == "unknown"`.

`GET /endpoints`:
- Update existing tests' mock rows and assertions to include `file_path`/`function_name`.
- Add `test_get_endpoints_includes_file_path_and_function_name` — mock `conn.fetch` to return one row with `file_path="routers/users.py"`, `function_name="get_user"` (plus the existing columns), call `GET /endpoints?service_id=1`, assert both fields appear unchanged in the JSON response.

`GET /endpoints/{id}/impact-analysis`:
- Update `test_get_impact_analysis_returns_consumers` — mock rows include `caller_function_name`/`caller_file_path`; assert they appear in the response.

### Frontend

`frontend/__tests__/DependencyGraph.test.jsx` — rewrite for the raw-node-in contract:
- `test_dependency_graph_renders_endpoint_and_caller_leaf_nodes` — pass raw `nodes`/`edges` (API shape) for one endpoint + one caller; mock `@xyflow/react`'s `ReactFlow` to render each node's `data.label`; assert both leaf labels appear.
- `test_dependency_graph_groups_leaf_nodes_under_service_and_file` — assert the rendered node list (captured via the `ReactFlow` mock) includes group nodes whose `id` matches `service_name` and `"{service_name}:{file_path}"`, and that the leaf node's `parentId` matches the file group id.
- `test_dependency_graph_handles_null_file_path` — a node with `file_path: null` → grouped under a `"(unknown)"` file group id, no crash.
- `test_dependency_graph_onNodeClick_forwards_full_node_data` — clicking a mocked leaf node fires `onNodeClick` with `node.data.node_type`, `node.data.method`, etc. populated from the original API node.
- `test_dependency_graph_tiers_caller_only_above_provider_only_service` — three services: `caller-only-svc` (a `caller` node whose `service_name` never appears on any `endpoint` node), `provider-only-svc` (an `endpoint` node whose `service_name` never appears on any `caller` node), and one edge connecting them. Capture the two service group nodes' rendered `position.y` (or `style`/props exposing it through the `ReactFlow` mock) and assert `caller-only-svc`'s group `y` is strictly less than `provider-only-svc`'s group `y` (top vs. bottom tier).
- `test_dependency_graph_tiers_mixed_service_in_middle` — a service that owns both a `caller` node and an `endpoint` node (i.e. it appears in both `providerServices` and `callerServices`) → its group node's `y` is strictly between the caller-only and provider-only tiers' `y` values from the previous test's setup.

`frontend/__tests__/ImpactPanel.test.jsx` — rewrite (this file is already broken against the current component; fix it as part of this spec rather than leaving it broken):
- Update `defaultProps` to `{ endpointId, method: 'GET', path: '/users/{id}', functionName: 'get_user', onClose }`.
- `test_impact_panel_shows_loading_state`, `_shows_error_state`, `_calls_onClose_on_button_click`, `_refetches_when_endpointId_changes` — update text assertions to match the component's actual current strings (`"No consumers found"` no trailing period, `"Failed to load consumers."` with a period, close button `aria-label="Close panel"`).
- `test_impact_panel_shows_consumer_list` — mock consumer includes `caller_function_name`/`caller_file_path`; assert the rendered row text is `"{caller_function_name} in {caller_file_path} (order-service)"`.
- `test_impact_panel_consumer_row_falls_back_when_caller_context_missing` — a consumer with `caller_function_name: null, caller_file_path: null` → row renders `"unknown in unknown file (order-service)"`.
- `test_impact_panel_shows_function_name_above_method_path` — assert `functionName` prop text appears in the rendered header.
- Delete the `test_static_source_badge_is_gray` / `test_logs_source_badge_is_green` tests outright — the current `ImpactPanel.jsx` renders the `source` badge with a single fixed style (`bg-prussian-400`) regardless of `static`/`logs`, so these two tests assert behavior that does not exist in the component (they are part of why this file already fails today) — keep only assertions that match real rendered behavior.

`frontend/__tests__/GraphPageInner_independent.test.jsx` and `frontend/__tests__/ImpactPanel_spec10.test.jsx`:
- Update every mocked `fetchGraph` resolution from `{id, name}` nodes and `endpoint_method`/`endpoint_path` edges to the new `GraphNode`/`GraphEdge` shape (`id: "ep:10"`, `node_type: "endpoint"`, `label`, `method`, `path`, `function_name`, `file_path`, `service_name`, `service_id`; edges with `call_count`/`last_seen_at` only, no `endpoint_method`/`endpoint_path`).
- Update the mocked `DependencyGraph` stand-in to read `n.node_type`/`n.data.node_type` per the new contract (raw nodes in, or however the test chooses to stub the boundary — the point being the id scheme `ep:`/`caller:` replaces `endpoint-`/bare-numeric ids).
- Update `handleNodeClick` assertions: clicking an endpoint leaf opens `ImpactPanel` with `method`/`path`/`functionName` props (not `endpointLabel`).

## Done when
- [ ] Migration `v2_11_endpoint_nodes` applied — `endpoints.file_path`, `endpoints.function_name`, `consumer_edges.caller_file_path`, `consumer_edges.caller_function_name` all exist and are nullable.
- [ ] `extract_route_decorators`, `extract_js_routes` return a `function_name` key in every dict.
- [ ] `extract_http_calls` returns a `caller_function_name` key; `extract_js_http_calls` returns `list[dict]` with `url`/`file_path`/`caller_function_name` keys (no longer `list[str]`).
- [ ] `_enclosing_py_function_name` and `_enclosing_js_function_name` exist in `code_parser.py` with the exact behavior described (walk `.parent` links; JS variant also resolves named arrow functions via their `variable_declarator` parent).
- [ ] `analyze.py` passes `file_path`/`function_name` on every endpoint insert and `caller_file_path`/`caller_function_name` on every edge insert; the endpoint upsert SQL is `DO UPDATE ... RETURNING id` with no dead fallback-`SELECT` branch remaining.
- [ ] `GET /graph` runs exactly one query (CLAUDE.md's canonical joined SQL) and returns deduplicated `node_type: "endpoint"` / `"caller"` nodes plus one edge per `consumer_edges` row.
- [ ] `backend/models.py`'s `GraphNode`, `GraphEdge`, `EndpointOut`, `ConsumerOut` match CLAUDE.md's Pydantic models section exactly.
- [ ] `GET /endpoints` and `GET /endpoints/{id}/impact-analysis` return the new columns.
- [ ] `DependencyGraph.jsx` accepts raw API `GraphNode[]`/`GraphEdge[]` and renders a 3-level service-group → file-group → leaf-node hierarchy via `parentId`, laid out with `@dagrejs/dagre` (service tiering: caller-only top, provider-only bottom, both in the middle).
- [ ] `ImpactPanel.jsx` accepts `method`/`path`/`functionName` props (no more `endpointLabel`/`parseLabel`) and renders each consumer as `"{caller_function_name} in {caller_file_path} ({service_name})"`.
- [ ] `GraphPageInner.jsx` no longer builds React Flow nodes itself — it passes filtered raw API nodes/edges to `DependencyGraph`.
- [ ] `frontend/lib/graphFilter.js` filters on `node.node_type`/`node.label` (raw API `GraphNode` fields) instead of `!node.id.startsWith('endpoint-')`/`node.data.label`.
- [ ] `@dagrejs/dagre` is in `frontend/package.json` dependencies and `package-lock.json`.
- [ ] Every test case listed above passes, including the updated (previously stale) `ImpactPanel.test.jsx`.
- [ ] No TypeScript — all frontend files remain `.js`/`.jsx`.
- [ ] No hardcoded credentials anywhere.
- [ ] Follows CLAUDE.md conventions — raw asyncpg (no ORM), `set_rls_context` first in every transaction, `ssr:false` dynamic import for `DependencyGraph` unchanged, ES2022 JS, endpoint-level graph nodes per the "Key decisions" section.
