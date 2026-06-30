# Spec v2-05 — JS/TS Parser

## Goal
Extend `backend/analysis/code_parser.py` with two new functions for JavaScript/TypeScript files and update the analyze pipeline so `.js`, `.jsx`, `.ts`, and `.tsx` files are parsed alongside `.py` files.

## Depends on
- Spec v2-04 (recursive scan) — service folder discovery must be fully working

## Context
The existing `code_parser.py` only handles Python: `extract_route_decorators` finds FastAPI/Flask route decorators, and `extract_http_calls` finds `requests`/`httpx` calls. The analyze route in `analyze.py` only globs for `*.py` files.

This spec adds JS/TS equivalents so Express, Next.js, and JS HTTP-client call sites are also discovered. No new packages are needed — `tree_sitter_languages` already bundles the `javascript` and `typescript` grammars.

## Files to create
None.

## Files to edit
- `backend/analysis/code_parser.py` — add `extract_js_routes`, `extract_js_http_calls`, `detect_service_language`
- `backend/routers/analyze.py` — process JS/TS files in both the route discovery and edge discovery passes
- `backend/tests/test_code_parser.py` — add JS/TS test cases

---

## Implementation details

### backend/analysis/code_parser.py

Add the following at the top of the file alongside the existing Python imports and parsers:

```python
import os
import re
from tree_sitter_languages import get_language, get_parser

JS_LANGUAGE  = get_language("javascript")
TS_LANGUAGE  = get_language("typescript")
js_parser    = get_parser("javascript")
ts_parser    = get_parser("typescript")
```

Add a helper that returns the right (language, parser) pair based on file extension:

```python
def _get_js_parser(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".ts", ".tsx"}:
        return TS_LANGUAGE, ts_parser
    return JS_LANGUAGE, js_parser
```

---

#### `extract_js_routes(file_path: str) -> list[dict]`

Returns a list of dicts, each `{"method": str, "path": str, "spec_source": str}`.

Two sub-cases handled inside one function:

**Case A — Express-style route declarations**

Match calls of the form `app.get(...)`, `router.post(...)`, `express.delete(...)`, etc.
The `spec_source` for these is `"decorator_js"`.

tree-sitter query (JavaScript and TypeScript share the same grammar node names here):

```
(call_expression
  function: (member_expression
    object: (identifier)
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path))
```

**Trade-off note (intentional):** This query matches any member call whose first argument is a string literal and whose method name is get/post/put/delete — it does not restrict the object name. Express apps use arbitrary variable names (`app`, `router`, `api`, `v1`, etc.) so an object-name allowlist would miss valid routes. The method-name filter combined with the path being a string literal is specific enough for static analysis, and `IGNORED_DIRS` filtering in `analyze.py` (see below) eliminates the main source of false positives (`node_modules/`). This is a deliberate heuristic — do not add object-name filtering.

Processing:
1. `@method` text must be in `{"get", "post", "put", "delete"}` (case-insensitive, uppercased for storage).
2. `@path` is a `string` node. Extract its string value: take `node.text.decode("utf-8")`, then `ast.literal_eval()` it (same pattern as `_node_string_value`). If it raises, skip.
3. Skip if the raw text starts with a backtick (template literal) — `raw.startswith("`")`. (In JS tree-sitter, template literals are `template_string` nodes and wouldn't match `(string)` in the query anyway, but this check is a safe guard.)
4. Append `{"method": METHOD.upper(), "path": path_value, "spec_source": "decorator_js"}`.

**Case B — Next.js App Router file-based routes**

A file is a Next.js route file if its path (normalised to forward slashes) contains `/app/api/` **and** the basename is `route.js`, `route.jsx`, `route.ts`, or `route.tsx`.

If both conditions are true, derive the HTTP path from the file path:

```python
def _nextjs_api_path(file_path: str) -> str | None:
    normalized = file_path.replace("\\", "/")
    marker = "/app/api/"
    idx = normalized.find(marker)
    if idx == -1:
        return None
    after = normalized[idx + len(marker):]
    # strip /route.{ext} or route.{ext} (root route)
    for suffix in ("/route.js", "/route.jsx", "/route.ts", "/route.tsx"):
        if after.endswith(suffix):
            after = after[: -len(suffix)]
            break
    else:
        for bare in ("route.js", "route.jsx", "route.ts", "route.tsx"):
            if after == bare:
                after = ""
                break
        else:
            return None
    # [id] → {id}, [...slug] → {slug}
    after = re.sub(r"\[\.\.\.([^\]]+)\]", r"{\1}", after)
    after = re.sub(r"\[([^\]]+)\]", r"{\1}", after)
    return "/api/" + after if after else "/api/"
```

Then parse the file with the JS/TS tree-sitter grammar and find exported HTTP-method functions.
Match both named function exports and variable exports:

```
(export_statement
  declaration: (function_declaration
    name: (identifier) @name))

(export_statement
  declaration: (lexical_declaration
    (variable_declarator
      name: (identifier) @name)))
```

From the matches, collect any `@name` whose text is in `{"GET", "POST", "PUT", "DELETE"}`.
For each matched method, append `{"method": name_text, "path": derived_path, "spec_source": "nextjs_route"}`.

**Combined logic:**

```python
def extract_js_routes(file_path: str) -> list[dict]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        results = []

        # Case A — Express routes
        query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier)
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path))
""")
        for _, match in query.matches(tree.root_node):
            method_node = match.get("method")
            path_node   = match.get("path")
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
            results.append({"method": method, "path": path_value, "spec_source": "decorator_js"})

        # Case B — Next.js file-based routes
        api_path = _nextjs_api_path(file_path)
        if api_path is not None:
            fn_query = lang.query("""
(export_statement
  declaration: (function_declaration
    name: (identifier) @name))
(export_statement
  declaration: (lexical_declaration
    (variable_declarator
      name: (identifier) @name)))
""")
            for _, match in fn_query.matches(tree.root_node):
                name_node = match.get("name")
                if name_node is None:
                    continue
                name_text = name_node.text.decode("utf-8")
                if name_text in {"GET", "POST", "PUT", "DELETE"}:
                    results.append({"method": name_text, "path": api_path, "spec_source": "nextjs_route"})

        return results
    except Exception:
        return []
```

---

#### `extract_js_http_calls(file_path: str) -> list[str]`

Returns a list of URL strings (not dicts — unlike the Python `extract_http_calls`).

Detects two call patterns:

**Pattern 1 — `fetch("url")`** (bare `fetch` identifier):

```
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (string) @url))
```

Filter: `@fn` text must equal `"fetch"`.

**Pattern 2 — `axios.get("url")`, `axios.post(...)`, etc.** (member call on `axios`):

```
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @url))
```

Filter: `@lib` must be `"axios"` and `@method` must be in `{"get", "post", "put", "delete"}`.

For both patterns:
- Extract `@url` node text and `ast.literal_eval()` it; skip if it raises or is not a string.
- Skip template literals (backtick strings).
- Append the plain string URL to the result list.

```python
def extract_js_http_calls(file_path: str) -> list[str]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        results = []

        # fetch("url")
        fetch_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (string) @url))
""")
        for _, match in fetch_query.matches(tree.root_node):
            fn_node  = match.get("fn")
            url_node = match.get("url")
            if fn_node is None or url_node is None:
                continue
            if fn_node.text.decode("utf-8") != "fetch":
                continue
            raw = url_node.text.decode("utf-8")
            if raw.startswith("`"):
                continue
            try:
                url = ast.literal_eval(raw)
            except Exception:
                continue
            if isinstance(url, str):
                results.append(url)

        # axios.get/post/put/delete("url")
        axios_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @url))
""")
        for _, match in axios_query.matches(tree.root_node):
            lib_node    = match.get("lib")
            method_node = match.get("method")
            url_node    = match.get("url")
            if lib_node is None or method_node is None or url_node is None:
                continue
            if lib_node.text.decode("utf-8") != "axios":
                continue
            if method_node.text.decode("utf-8") not in {"get", "post", "put", "delete"}:
                continue
            raw = url_node.text.decode("utf-8")
            if raw.startswith("`"):
                continue
            try:
                url = ast.literal_eval(raw)
            except Exception:
                continue
            if isinstance(url, str):
                results.append(url)

        return results
    except Exception:
        return []
```

---

#### `detect_service_language(folder_path: str) -> str`

Used by `analyze.py` to determine the `language` column value for a service.

```python
def detect_service_language(folder_path: str) -> str:
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.endswith(".py"):
                return "python"
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.endswith((".js", ".jsx", ".ts", ".tsx")):
                return "javascript"
    return "unknown"
```

Python wins if any `.py` file is found anywhere in the folder. Otherwise falls back to javascript if any JS/TS file exists. Returns `"unknown"` if neither.

---

### backend/routers/analyze.py

**Import additions** at the top:

```python
from analysis.code_parser import (
    extract_route_decorators,
    extract_http_calls,
    extract_js_routes,
    extract_js_http_calls,
    detect_service_language,
)
from analysis.scanner import IGNORED_DIRS
```

**New helper function** — add after the existing `_safe_path` and `_extract_path` helpers (before the `router` declaration and `UPSERT_EDGE_SQL` constant):

```python
def _is_in_ignored_dir(file_path: str, root: str) -> bool:
    """Return True if any path component between root and file_path is in IGNORED_DIRS."""
    rel = os.path.relpath(file_path, root)
    return any(part in IGNORED_DIRS for part in rel.split(os.sep))
```

**`UPSERT_EDGE_SQL` constant** — add at module level after the helpers and before `router = APIRouter()`:

```python
UPSERT_EDGE_SQL = """INSERT INTO consumer_edges
    (caller_service_id, endpoint_id, last_seen_at, call_count, source)
VALUES ($1, $2, NOW(), 1, $3)
ON CONFLICT (caller_service_id, endpoint_id)
DO UPDATE SET last_seen_at = NOW(), source = EXCLUDED.source"""

router = APIRouter()
```

**Route discovery pass** — replace the existing Python-only glob with a combined scan:

Current code (inside the first transaction loop):
```python
for py_file in glob.glob(os.path.join(folder_path, "*.py")):
    if not _safe_path(py_file, tmp_dir):
        continue
    for ep in extract_route_decorators(py_file):
        discovered.append({
            "method": ep["method"],
            "path": ep["path"],
            "spec_source": "decorator",
        })
```

Replace with:
```python
# Python route decorators
for py_file in glob.glob(os.path.join(folder_path, "**", "*.py"), recursive=True):
    if not _safe_path(py_file, tmp_dir):
        continue
    if _is_in_ignored_dir(py_file, folder_path):
        continue
    for ep in extract_route_decorators(py_file):
        discovered.append({
            "method": ep["method"],
            "path": ep["path"],
            "spec_source": "decorator",
        })

# JS/TS route decorators and Next.js file-based routes
for pattern in ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"):
    for js_file in glob.glob(os.path.join(folder_path, pattern), recursive=True):
        if not _safe_path(js_file, tmp_dir):
            continue
        if _is_in_ignored_dir(js_file, folder_path):
            continue
        for ep in extract_js_routes(js_file):
            discovered.append(ep)  # already has method, path, spec_source
```

**Language detection** — replace the hardcoded `"python"` string in the INSERT:

```python
# Before:
row = await conn.fetchrow(
    "...",
    service_name, "python", request.repo_url, user_id, repo_id,
)

# After:
lang = detect_service_language(folder_path)
row = await conn.fetchrow(
    "...",
    service_name, lang, request.repo_url, user_id, repo_id,
)
```

**Edge discovery pass** — extend the Python-only glob to also process JS/TS files:

Current code (inside the third transaction loop):
```python
py_files = glob.glob(os.path.join(folder_path, "*.py"))
for py_file in py_files:
    if not _safe_path(py_file, tmp_dir):
        continue
    calls = extract_http_calls(py_file)
    for call in calls:
        url_path = _extract_path(call["url"])
        ...
```

Replace with:
```python
# Python HTTP calls
for py_file in glob.glob(os.path.join(folder_path, "**", "*.py"), recursive=True):
    if not _safe_path(py_file, tmp_dir):
        continue
    if _is_in_ignored_dir(py_file, folder_path):
        continue
    for call in extract_http_calls(py_file):
        url_path = _extract_path(call["url"])
        if not url_path:
            continue
        matched_path = match_url_to_endpoint(url_path, known_paths)
        if matched_path is None:
            continue
        matched_endpoint = next(
            (e for e in known_endpoints if e["path"] == matched_path), None
        )
        if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
            continue
        await conn.execute(UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static")
        edges_count += 1

# JS/TS HTTP calls (extract_js_http_calls returns list[str], not list[dict])
for pattern in ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"):
    for js_file in glob.glob(os.path.join(folder_path, pattern), recursive=True):
        if not _safe_path(js_file, tmp_dir):
            continue
        if _is_in_ignored_dir(js_file, folder_path):
            continue
        for url in extract_js_http_calls(js_file):
            url_path = _extract_path(url)
            if not url_path:
                continue
            matched_path = match_url_to_endpoint(url_path, known_paths)
            if matched_path is None:
                continue
            matched_endpoint = next(
                (e for e in known_endpoints if e["path"] == matched_path), None
            )
            if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
                continue
            await conn.execute(UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static")
            edges_count += 1
```

> Note: `UPSERT_EDGE_SQL` is defined at module level (see Import additions section above). The existing inline `await conn.execute(...)` block in the edge loop must be replaced with `await conn.execute(UPSERT_EDGE_SQL, ...)` as shown above.

---

### backend/tests/test_code_parser.py

Add the following test functions. Import the new functions at the top:

```python
from analysis.code_parser import (
    extract_route_decorators,
    extract_http_calls,
    extract_js_routes,
    extract_js_http_calls,
    detect_service_language,
)
```

**express route tests:**

- `test_js_express_get` — writes `app.get('/users', handler)` to a `.js` file; asserts result contains `{"method": "GET", "path": "/users", "spec_source": "decorator_js"}`
- `test_js_express_post` — writes `router.post('/orders', handler)` to a `.js` file; asserts `method=POST`
- `test_js_express_put` — writes `app.put('/items/:id', handler)`; asserts `method=PUT`, `path='/items/:id'`
- `test_js_express_delete` — writes `app.delete('/users/:id', handler)`; asserts `method=DELETE`
- `test_js_express_unknown_method` — writes `app.patch('/x', handler)`; asserts result is `[]` (PATCH is not tracked)
- `test_js_express_template_literal_path_skipped` — writes `` app.get(`/users/${id}`, h) ``; asserts result is `[]`
- `test_ts_express_route` — writes Express route to a `.ts` file; asserts it is parsed correctly (TS grammar)

**Next.js route tests:**

- `test_nextjs_get_route` — creates a temp file at `tmp_path/app/api/users/route.js` containing `export async function GET(req) {}` and `export async function POST(req) {}`; asserts result contains both `{"method": "GET", "path": "/api/users", "spec_source": "nextjs_route"}` and `POST`
- `test_nextjs_dynamic_route` — file at `tmp_path/app/api/users/[id]/route.js` with `export function GET(req) {}`; asserts `path="/api/users/{id}"`
- `test_nextjs_catch_all_route` — file at `tmp_path/app/api/[...slug]/route.ts` with `export function GET() {}`; asserts `path="/api/{slug}"`
- `test_nextjs_non_route_file_skipped` — creates `tmp_path/app/api/users/helpers.js` containing `export function helper() { return 42; }` (no Express routes, no HTTP method exports); asserts result is `[]`
- `test_nextjs_no_http_exports` — file at `tmp_path/app/api/users/route.js` with only `export function helper() {}`; asserts result is `[]`

**JS HTTP call tests:**

- `test_js_fetch_call` — writes `fetch("http://user-service/users/1")` to a `.js` file; asserts result is `["http://user-service/users/1"]`
- `test_js_axios_get` — writes `axios.get("http://svc/users/1")` to a `.js` file; asserts URL in result
- `test_js_axios_post` — writes `axios.post("http://svc/orders")` to a `.js` file; asserts URL in result
- `test_js_axios_delete` — writes `axios.delete("http://svc/items/1")`; asserts URL in result
- `test_js_fetch_template_literal_skipped` — writes `` fetch(`http://svc/users/${id}`) ``; asserts result is `[]`
- `test_js_fetch_variable_url_skipped` — writes `const url = "http://svc"; fetch(url)`; asserts result is `[]`
- `test_js_multiple_http_calls` — file with both `fetch(...)` and `axios.get(...)`; asserts both URLs are in result
- `test_ts_fetch_call` — writes `fetch("http://svc/path")` to a `.ts` file; asserts URL in result
- `test_js_http_calls_no_calls` — file with no fetch/axios; asserts result is `[]`
- `test_js_routes_file_not_found` — `extract_js_routes("/nonexistent.js")` returns `[]`
- `test_js_http_calls_file_not_found` — `extract_js_http_calls("/nonexistent.ts")` returns `[]`

**detect_service_language tests:**

- `test_detect_language_python` — `tmp_path` contains `main.py`; asserts `detect_service_language(str(tmp_path)) == "python"`
- `test_detect_language_javascript` — `tmp_path` contains `index.js`; asserts `detect_service_language(str(tmp_path)) == "javascript"`
- `test_detect_language_unknown` — `tmp_path` is empty; asserts `detect_service_language(str(tmp_path)) == "unknown"`
- `test_detect_language_python_wins` — `tmp_path` contains both `main.py` and `index.js`; asserts result is `"python"` (Python takes priority over JS)
- `test_detect_language_ts_counts_as_javascript` — `tmp_path` contains `server.ts`; asserts result is `"javascript"`

---

## Done when

- [ ] `extract_js_routes` and `extract_js_http_calls` are implemented in `code_parser.py`
- [ ] `detect_service_language` is implemented in `code_parser.py`
- [ ] `code_parser.py` imports `os` and `re` (in addition to the existing `ast` and tree-sitter imports)
- [ ] `analyze.py` processes `.js`, `.jsx`, `.ts`, `.tsx` files in both the route discovery pass and edge discovery pass
- [ ] `analyze.py` uses `detect_service_language` instead of hardcoding `"python"`
- [ ] The glob patterns in `analyze.py` are recursive (`**/*.py`, `**/*.js`, etc.) using `recursive=True`
- [ ] All recursive glob loops in `analyze.py` call `_is_in_ignored_dir(file_path, folder_path)` and skip files inside ignored directories
- [ ] `_is_in_ignored_dir` helper is defined in `analyze.py` and `IGNORED_DIRS` is imported from `analysis.scanner`
- [ ] `UPSERT_EDGE_SQL` is defined at module level in `analyze.py` (after helpers, before `router = APIRouter()`)
- [ ] All test cases listed above pass (`python -m pytest tests/test_code_parser.py -v`)
- [ ] `extract_js_http_calls` returns `list[str]` (URL strings, not dicts)
- [ ] `extract_js_routes` returns `list[dict]` with keys `method`, `path`, `spec_source`
- [ ] No TypeScript anywhere in the backend
- [ ] No hardcoded credentials
- [ ] `spec_source` values are exactly `"decorator_js"` (Express) or `"nextjs_route"` (Next.js file routes)
