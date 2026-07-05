# Spec v2-10 — Template Literal & F-String URL Detection

## Goal

Extend `extract_http_calls` (Python) and `extract_js_http_calls` (JS/TS) in `backend/analysis/code_parser.py` so HTTP calls whose URL is a JS template literal or a Python f-string are detected and reduced to a path pattern (with `{param}` placeholders for dynamic segments) instead of being silently skipped.

## Depends on

- Spec v2-05 (JS/TS parser) — `extract_js_http_calls` must already exist before this spec can extend it

## Context

Real services rarely hardcode plain string URLs for outbound calls. They build them from an env-var host and/or a dynamic path segment:

```js
fetch(`${API_HOST}/users`)
fetch(`/users/${id}`)
axios.get(`http://svc/users/${id}`)
```

```python
requests.get(f"http://{HOST}/users")
requests.get(f"http://svc/users/{user_id}")
```

Today both functions only match plain string literals (`(string)` in the JS query, `ast.literal_eval`-able strings in Python) and explicitly skip anything that looks like a template literal or f-string. This means a large fraction of real-world consumer edges are invisible to the graph. This spec closes that gap by reconstructing a matchable path pattern from the dynamic parts, without changing what either function returns to its caller (`backend/routers/analyze.py`), so no downstream code needs to change. The reconstructed pattern (e.g. `/users/{param}`) already round-trips correctly through `url_matcher.match_url_to_endpoint`, because `{param}` satisfies the `[^/]+` regex substituted for `{id}`-style placeholders in known endpoint paths.

This is static-analysis-only, per CLAUDE.md ("Static analysis only" — no log ingestion, no runtime tracing). Detecting call sites more accurately at parse time is in scope; nothing about the `source` column or v3 features changes.

## Files to edit

- `backend/analysis/code_parser.py` — extend `extract_http_calls` to handle f-string url nodes; extend `extract_js_http_calls` to also match `template_string` url arguments to `fetch()` / `axios.*()`; add three new helper functions (details below).
- `backend/tests/test_code_parser.py` — update the two existing tests that assert template/f-string URLs are skipped (they now assert reconstruction instead), and add the five new test cases listed below.

## Implementation details

### New helper: `_extract_path_from_pattern(pattern: str) -> str | None`

Module-level function in `code_parser.py`, used by both the Python and JS reconstruction paths.

```python
def _extract_path_from_pattern(pattern: str) -> str | None:
    scheme_idx = pattern.find("://")
    search_from = scheme_idx + 3 if scheme_idx != -1 else 0
    slash_idx = pattern.find("/", search_from)
    if slash_idx == -1:
        return None
    return pattern[slash_idx:]
```

Behavior:
- If the pattern contains a scheme separator (`://`), search for the first `/` *after* it — this skips the `//` of the scheme itself and any host segment (static or `{param}`), landing on the real path.
- If there is no `://` (a bare template like `{param}/users` or a path-only string like `/users/{param}`), search for the first `/` from the start.
- Returns `None` if no `/` is found at all (e.g. a call with no path, such as a bare host) — callers must skip results where this is `None`.

Examples:
- `"http://{param}/users"` → `"/users"`
- `"http://svc/users/{param}"` → `"/users/{param}"`
- `"{param}/users"` → `"/users"`
- `"/users/{param}"` → `"/users/{param}"`

### New helper (JS): `_reconstruct_template_string(node, source: bytes) -> str`

Module-level function. Walks a `template_string` node's children and rebuilds the literal text with `{param}` substituted for every `template_substitution` child. In the pinned `tree-sitter-languages==1.10.2` grammar, literal text between substitutions is **not** exposed as a named/anonymous child node — it must be sliced directly out of the raw source bytes using byte offsets.

```python
def _reconstruct_template_string(node, source: bytes) -> str:
    parts = []
    cursor = node.start_byte + 1   # skip opening backtick
    end = node.end_byte - 1        # exclude closing backtick
    for child in node.children:
        if child.type == "template_substitution":
            if child.start_byte > cursor:
                parts.append(source[cursor:child.start_byte].decode("utf-8"))
            parts.append("{param}")
            cursor = child.end_byte
    if cursor < end:
        parts.append(source[cursor:end].decode("utf-8"))
    return "".join(parts)
```

### New helper (Python): `_reconstruct_fstring(node) -> str`

Module-level function. In the pinned `tree-sitter-python` grammar, an f-string parses as a `string` node (same node type as a plain string) whose children include `string_content` nodes (literal text) and `interpolation` nodes (the `{expr}` parts) between `string_start` (`f"`/`f'`) and `string_end` markers. Unlike JS, `string_content` segments already exist as their own named child nodes, so no manual byte-slicing is needed.

```python
def _reconstruct_fstring(node) -> str:
    parts = []
    for child in node.children:
        if child.type == "string_content":
            parts.append(child.text.decode("utf-8"))
        elif child.type == "interpolation":
            parts.append("{param}")
    return "".join(parts)
```

### Edit: `extract_http_calls(file_path: str) -> list[dict]`

Keep `HTTP_CALL_QUERY` unchanged (it already captures `(string) @url`, and f-strings parse as `string` nodes in this grammar, so no query change is needed — this matches how `_is_fstring` already inspects the same captured node).

Replace the current skip:

```python
if _is_fstring(url_node):
    continue
```

with:

```python
if _is_fstring(url_node):
    pattern = _reconstruct_fstring(url_node)
    path = _extract_path_from_pattern(pattern)
    if path is None:
        continue
    results.append({"url": path})
    continue
```

The non-f-string branch below (`_node_string_value` + `ast.literal_eval`) is unchanged. Return type is still `list[dict]` with a single `"url"` key per entry — identical shape to today, just with a `{param}`-bearing path string in place of a skip for f-strings.

### Edit: `extract_js_http_calls(file_path: str) -> list[str]`

Keep the existing `fetch_query` and `axios_query` (matching `(string) @url`) exactly as they are — plain string literal calls are unaffected.

Add two more queries in the same function, matching `template_string` in the URL argument position instead of `string`:

```python
fetch_template_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (template_string) @url))
""")
for _, match in fetch_template_query.matches(tree.root_node):
    fn_node = match.get("fn")
    url_node = match.get("url")
    if fn_node is None or url_node is None:
        continue
    if fn_node.text.decode("utf-8") != "fetch":
        continue
    pattern = _reconstruct_template_string(url_node, source)
    path = _extract_path_from_pattern(pattern)
    if path is not None:
        results.append(path)

axios_template_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (template_string) @url))
""")
for _, match in axios_template_query.matches(tree.root_node):
    lib_node = match.get("lib")
    method_node = match.get("method")
    url_node = match.get("url")
    if lib_node is None or method_node is None or url_node is None:
        continue
    if lib_node.text.decode("utf-8") != "axios":
        continue
    if method_node.text.decode("utf-8") not in {"get", "post", "put", "delete"}:
        continue
    pattern = _reconstruct_template_string(url_node, source)
    path = _extract_path_from_pattern(pattern)
    if path is not None:
        results.append(path)
```

`source` is the same `bytes` object already read at the top of `extract_js_http_calls` (`source = open(file_path, "rb").read()`) — reuse it, do not re-read the file.

Return type is still `list[str]` — identical shape to today, just with `{param}`-bearing path strings appended in place of the previous skip.

### No changes needed elsewhere

- `backend/routers/analyze.py` — `_extract_path(url)` calls `urlparse(url).path`. Since both functions now return path-only strings (not full URLs) for the template/f-string cases, `urlparse(...).path` on an already-path-only string returns it unchanged — verified this is idempotent for strings like `/users/{param}`.
- `backend/analysis/url_matcher.py` — `match_url_to_endpoint` already treats `{param}` the same as any other `{...}` placeholder text: the regex built from known endpoint paths (`\{[^}]+\}` → `[^/]+`) is applied to the *known* path, and the literal caller path (which may itself contain the literal substring `{param}`) is matched against it with `re.fullmatch`. `{param}` is just non-slash characters, so it matches `[^/]+` like any other segment. No change needed.
- `extract_js_routes` and `extract_route_decorators` (route *declarations*, not calls) are out of scope for this spec — their existing template-literal / f-string skip behavior is unchanged.

## Test cases

Add to `backend/tests/test_code_parser.py`.

Update these two existing tests (they currently assert a skip; the behavior they test has changed):

- `test_extract_fstring_url_reconstructed` (replaces `test_extract_fstring_url_skipped`) — `requests.get(f"http://svc/users/{user_id}")` → `extract_http_calls` returns `[{"url": "/users/{param}"}]`.
- `test_js_fetch_template_literal_reconstructed` (replaces `test_js_fetch_template_literal_skipped`) — `` fetch(`http://svc/users/${id}`) `` → `extract_js_http_calls` returns `["/users/{param}"]`.

New test cases:

- `test_js_fetch_template_env_host_static_path` — `` const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}/users`); `` → `extract_js_http_calls` returns `["/users"]`.
- `test_js_fetch_template_dynamic_path_segment` — `` const id = 1;\nfetch(`/users/${id}`); `` → `extract_js_http_calls` returns `["/users/{param}"]`.
- `test_js_axios_get_template_literal` — `` const id = 1;\naxios.get(`http://svc/users/${id}`); `` → result contains `"/users/{param}"`.
- `test_requests_get_fstring_host` — `HOST = "svc"\nresp = requests.get(f"http://{HOST}/users")` → `extract_http_calls` returns `[{"url": "/users"}]`.
- `test_requests_get_fstring_path_segment` — `user_id = 1\nresp = requests.get(f"http://svc/users/{user_id}")` → `extract_http_calls` returns `[{"url": "/users/{param}"}]`.
- `test_js_fetch_template_no_path_skipped` — `` fetch(`${API_HOST}`); `` (host only, no `/` anywhere in the reconstructed pattern) → `extract_js_http_calls` returns `[]` — exercises the `_extract_path_from_pattern` → `None` branch.
- `test_requests_get_fstring_no_path_skipped` — `HOST = "svc"\nresp = requests.get(f"http://{HOST}")` (host only, no path) → `extract_http_calls` returns `[]` — same `None` branch, Python side.
- `test_js_fetch_template_multiple_substitutions` — `` const id = 1;\nconst orderId = 2;\nfetch(`/users/${id}/orders/${orderId}`); `` → `extract_js_http_calls` returns `["/users/{param}/orders/{param}"]` — confirms repeated substitutions each become `{param}`.
- `test_requests_get_fstring_multiple_substitutions` — `user_id = 1\norder_id = 2\nresp = requests.get(f"http://svc/users/{user_id}/orders/{order_id}")` → `extract_http_calls` returns `[{"url": "/users/{param}/orders/{param}"}]` — same, Python side.
- `test_js_fetch_template_no_substitutions` — `` fetch(`/users`); `` (a template literal with zero `${}` substitutions) → `extract_js_http_calls` returns `["/users"]` — confirms the new `template_string` queries also match plain template literals, not just ones with dynamic segments.
- `test_ts_fetch_template_literal` — same source as `test_js_fetch_template_literal_reconstructed` but in a `.ts` file: `` fetch(`http://svc/users/${id}`); `` → `extract_js_http_calls` returns `["/users/{param}"]` — confirms the TS grammar parses `template_string` identically to JS (parity with the existing `test_ts_fetch_call`).

Leave unchanged (still valid, out of scope):

- `test_extract_variable_url_skipped` — a plain variable reference (not a template literal or f-string) is still skipped.
- `test_js_fetch_variable_url_skipped` — same, JS side.
- `test_js_express_template_literal_path_skipped` — this tests `extract_js_routes` (route declarations), which is out of scope for this spec.

## Done when

- [ ] `_extract_path_from_pattern`, `_reconstruct_template_string`, and `_reconstruct_fstring` exist in `backend/analysis/code_parser.py` with the exact signatures above.
- [ ] `extract_http_calls` reconstructs f-string URLs into a `{param}`-bearing path instead of skipping them; return type is unchanged (`list[dict]` with `"url"` key).
- [ ] `extract_js_http_calls` matches `template_string` URL arguments to `fetch()` and `axios.get/post/put/delete()` via two additional tree-sitter queries, reconstructing them into `{param}`-bearing paths; return type is unchanged (`list[str]`).
- [ ] `backend/routers/analyze.py` and `backend/analysis/url_matcher.py` are untouched — the caller pipeline works unmodified against the new return values.
- [ ] All test cases listed above pass, including the two updated tests and the eleven new ones (5 original + 2 no-path + 2 multiple-substitution + 1 no-substitution + 1 TS parity).
- [ ] `test_extract_variable_url_skipped`, `test_js_fetch_variable_url_skipped`, and `test_js_express_template_literal_path_skipped` still pass unmodified.
- [ ] No new dependencies added to `requirements.txt`.
- [ ] Follows CLAUDE.md conventions — static analysis only, no new query added for Python (f-strings already parse as `(string)` nodes matched by the existing `HTTP_CALL_QUERY`).
