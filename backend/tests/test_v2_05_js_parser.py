"""
Independent tests for v2-05 JS/TS parser.
Derived from reading backend/analysis/code_parser.py and backend/routers/analyze.py directly.
NOT based on the spec's "Test cases" section.
Does NOT reuse or reference backend/tests/test_code_parser.py.
"""
import os
import pathlib
import pytest

from analysis.code_parser import (
    extract_js_routes,
    extract_js_http_calls,
    detect_service_language,
)
from routers.analyze import _is_in_ignored_dir


# ─── extract_js_routes: Express-style routes ─────────────────────────────────

def test_extract_js_routes_express_get_returns_correct_dict(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/users', (req, res) => res.send('ok'));")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/users", "spec_source": "decorator_js", "function_name": None} in result


def test_extract_js_routes_express_post(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("router.post('/orders', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "POST", "path": "/orders", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_express_put(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("api.put('/items/:id', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "PUT", "path": "/items/:id", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_express_delete(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("v1.delete('/users/:id', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "DELETE", "path": "/users/:id", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_express_method_stored_uppercase(tmp_path: pathlib.Path):
    # The tree-sitter node text is "get" (lowercase); the function must uppercase it
    f = tmp_path / "routes.js"
    f.write_text("app.get('/health', handler);")
    result = extract_js_routes(str(f))
    assert len(result) >= 1
    assert result[0]["method"] == "GET"


def test_extract_js_routes_express_patch_not_included(tmp_path: pathlib.Path):
    # PATCH is not in the tracked method set {GET, POST, PUT, DELETE}
    f = tmp_path / "routes.js"
    f.write_text("app.patch('/x', handler);")
    result = extract_js_routes(str(f))
    assert result == []


def test_extract_js_routes_express_template_literal_path_skipped(tmp_path: pathlib.Path):
    # Paths that start with a backtick must be skipped
    f = tmp_path / "routes.js"
    f.write_text("const id = 1;\napp.get(`/users/${id}`, handler);")
    result = extract_js_routes(str(f))
    assert result == []


def test_extract_js_routes_express_arbitrary_object_name_accepted(tmp_path: pathlib.Path):
    # The implementation does NOT restrict the object name (app, router, api, v1, …)
    f = tmp_path / "routes.js"
    f.write_text("myCustomRouter.get('/ping', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/ping", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_express_spec_source_is_decorator_js(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/x', handler);")
    result = extract_js_routes(str(f))
    assert len(result) == 1
    assert result[0]["spec_source"] == "decorator_js"


def test_extract_js_routes_express_multiple_routes_all_captured(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text(
        "app.get('/users', listUsers);\n"
        "app.post('/users', createUser);\n"
        "app.delete('/users/:id', deleteUser);\n"
    )
    result = extract_js_routes(str(f))
    methods = {r["method"] for r in result}
    paths = {r["path"] for r in result}
    assert methods == {"GET", "POST", "DELETE"}
    assert "/users" in paths
    assert "/users/:id" in paths


def test_extract_js_routes_express_ts_file(tmp_path: pathlib.Path):
    # .ts extension must use the TypeScript grammar and still find Express routes
    f = tmp_path / "routes.ts"
    f.write_text("app.get('/profile', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/profile", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_express_jsx_file(tmp_path: pathlib.Path):
    # .jsx uses the JavaScript grammar
    f = tmp_path / "routes.jsx"
    f.write_text("server.post('/submit', handler);")
    result = extract_js_routes(str(f))
    assert {"method": "POST", "path": "/submit", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_extract_js_routes_no_routes_returns_empty(tmp_path: pathlib.Path):
    f = tmp_path / "utils.js"
    f.write_text("function add(a, b) { return a + b; }")
    result = extract_js_routes(str(f))
    assert result == []


def test_extract_js_routes_empty_file_returns_empty(tmp_path: pathlib.Path):
    f = tmp_path / "empty.js"
    f.write_text("")
    result = extract_js_routes(str(f))
    assert result == []


def test_extract_js_routes_nonexistent_file_returns_empty():
    result = extract_js_routes("/does/not/exist/routes.js")
    assert result == []


def test_extract_js_routes_returns_list(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/x', handler);")
    result = extract_js_routes(str(f))
    assert isinstance(result, list)


def test_extract_js_routes_dict_has_required_keys(tmp_path: pathlib.Path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/x', handler);")
    result = extract_js_routes(str(f))
    assert len(result) == 1
    assert set(result[0].keys()) == {"method", "path", "spec_source", "function_name"}


# ─── extract_js_routes: Next.js App Router file-based routes ─────────────────

def test_extract_js_routes_nextjs_basic_get_route(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "users" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export async function GET(req) { return new Response('ok'); }")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/api/users", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_post_route(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "users" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export async function POST(req) { return new Response('created', {status: 201}); }")
    result = extract_js_routes(str(route_file))
    assert {"method": "POST", "path": "/api/users", "spec_source": "nextjs_route", "function_name": "POST"} in result


def test_extract_js_routes_nextjs_multiple_method_exports(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "users" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text(
        "export async function GET(req) { return new Response('ok'); }\n"
        "export async function POST(req) { return new Response('created'); }\n"
    )
    result = extract_js_routes(str(route_file))
    nextjs_results = [r for r in result if r["spec_source"] == "nextjs_route"]
    methods = {r["method"] for r in nextjs_results}
    assert methods == {"GET", "POST"}
    assert all(r["path"] == "/api/users" for r in nextjs_results)


def test_extract_js_routes_nextjs_dynamic_segment_bracket_to_brace(tmp_path: pathlib.Path):
    # [id] in directory name → {id} in HTTP path
    route_file = tmp_path / "app" / "api" / "users" / "[id]" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/api/users/{id}", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_catch_all_segment(tmp_path: pathlib.Path):
    # [...slug] → {slug}
    route_file = tmp_path / "app" / "api" / "[...slug]" / "route.ts"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/api/{slug}", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_root_api_path(tmp_path: pathlib.Path):
    # route.js directly under /app/api/ → path "/api"
    route_file = tmp_path / "app" / "api" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/api", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_const_export_detected(tmp_path: pathlib.Path):
    # export const GET = ... via lexical_declaration must also be caught
    route_file = tmp_path / "app" / "api" / "orders" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export const GET = async (req) => new Response('ok');")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/api/orders", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_spec_source_is_nextjs_route(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "ping" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert all(r["spec_source"] == "nextjs_route" for r in result)


def test_extract_js_routes_nextjs_tsx_route_file(tmp_path: pathlib.Path):
    # .tsx route files must also be parsed
    route_file = tmp_path / "app" / "api" / "items" / "route.tsx"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export async function DELETE(req: Request) { return new Response(); }")
    result = extract_js_routes(str(route_file))
    assert {"method": "DELETE", "path": "/api/items", "spec_source": "nextjs_route", "function_name": "DELETE"} in result


def test_extract_js_routes_nextjs_non_route_basename_not_detected(tmp_path: pathlib.Path):
    # helpers.js in /app/api/ — basename is not route.{ext} so no nextjs_route entries
    f = tmp_path / "app" / "api" / "users" / "helpers.js"
    f.parent.mkdir(parents=True)
    f.write_text("export function helper() { return 42; }")
    result = extract_js_routes(str(f))
    nextjs_results = [r for r in result if r["spec_source"] == "nextjs_route"]
    assert nextjs_results == []


def test_extract_js_routes_nextjs_non_http_export_not_included(tmp_path: pathlib.Path):
    # export function helper() {} must not appear — only GET/POST/PUT/DELETE are tracked
    route_file = tmp_path / "app" / "api" / "users" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function helper() { return 42; }")
    result = extract_js_routes(str(route_file))
    nextjs_results = [r for r in result if r["spec_source"] == "nextjs_route"]
    assert nextjs_results == []


def test_extract_js_routes_nextjs_delete_method_export(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "products" / "[id]" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function DELETE(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "DELETE", "path": "/api/products/{id}", "spec_source": "nextjs_route", "function_name": "DELETE"} in result


def test_extract_js_routes_nextjs_put_method_export(tmp_path: pathlib.Path):
    route_file = tmp_path / "app" / "api" / "products" / "[id]" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function PUT(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "PUT", "path": "/api/products/{id}", "spec_source": "nextjs_route", "function_name": "PUT"} in result


# ─── extract_js_routes: Next.js routes without /api/ prefix ─────────────────

def test_extract_js_routes_nextjs_app_root_route(tmp_path: pathlib.Path):
    # route.js directly under /app/ → path "/"
    route_file = tmp_path / "app" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_non_api_prefix(tmp_path: pathlib.Path):
    # app/users/route.js → /users  (no /api/ in path)
    route_file = tmp_path / "app" / "users" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/users", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_nested_non_api_path(tmp_path: pathlib.Path):
    # app/dashboard/settings/route.js → /dashboard/settings
    route_file = tmp_path / "app" / "dashboard" / "settings" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/dashboard/settings", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_extract_js_routes_nextjs_dynamic_non_api_path(tmp_path: pathlib.Path):
    # app/posts/[id]/route.js → /posts/{id}
    route_file = tmp_path / "app" / "posts" / "[id]" / "route.js"
    route_file.parent.mkdir(parents=True)
    route_file.write_text("export function GET(req) {}")
    result = extract_js_routes(str(route_file))
    assert {"method": "GET", "path": "/posts/{id}", "spec_source": "nextjs_route", "function_name": "GET"} in result


# ─── extract_js_http_calls: fetch() ─────────────────────────────────────────

def test_extract_js_http_calls_fetch_double_quoted(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('fetch("http://user-service/users/1");')
    result = extract_js_http_calls(str(f))
    assert result == [{"url": "http://user-service/users/1", "file_path": str(f), "caller_function_name": None}]


def test_extract_js_http_calls_fetch_single_quoted(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text("fetch('http://payment-service/charge');")
    result = extract_js_http_calls(str(f))
    assert result == [{"url": "http://payment-service/charge", "file_path": str(f), "caller_function_name": None}]


def test_extract_js_http_calls_fetch_template_literal_reconstructed(tmp_path: pathlib.Path):
    # Template literals are reconstructed into a {param}-bearing path (spec v2-10)
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfetch(`http://user-service/users/${id}`);")
    result = extract_js_http_calls(str(f))
    assert result == [{"url": "/users/{param}", "file_path": str(f), "caller_function_name": None}]


def test_extract_js_http_calls_non_fetch_identifier_skipped(tmp_path: pathlib.Path):
    # Only the bare identifier "fetch" matches — not other names
    f = tmp_path / "client.js"
    f.write_text('myFetch("http://svc/path");')
    result = extract_js_http_calls(str(f))
    assert result == []


def test_extract_js_http_calls_fetch_variable_argument_skipped(tmp_path: pathlib.Path):
    # fetch(url) where url is a variable — not a string literal — is not captured
    f = tmp_path / "client.js"
    f.write_text('const url = "http://svc/path";\nfetch(url);')
    result = extract_js_http_calls(str(f))
    assert result == []


# ─── extract_js_http_calls: axios.* ─────────────────────────────────────────

def test_extract_js_http_calls_axios_get(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('axios.get("http://user-service/users/1");')
    result = extract_js_http_calls(str(f))
    assert "http://user-service/users/1" in [c["url"] for c in result]


def test_extract_js_http_calls_axios_post(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('axios.post("http://order-service/orders");')
    result = extract_js_http_calls(str(f))
    assert "http://order-service/orders" in [c["url"] for c in result]


def test_extract_js_http_calls_axios_put(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('axios.put("http://svc/items/5");')
    result = extract_js_http_calls(str(f))
    assert "http://svc/items/5" in [c["url"] for c in result]


def test_extract_js_http_calls_axios_delete(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('axios.delete("http://svc/items/5");')
    result = extract_js_http_calls(str(f))
    assert "http://svc/items/5" in [c["url"] for c in result]


def test_extract_js_http_calls_axios_patch_skipped(tmp_path: pathlib.Path):
    # PATCH is not in the allowed set {"get", "post", "put", "delete"}
    f = tmp_path / "client.js"
    f.write_text('axios.patch("http://svc/items/5");')
    result = extract_js_http_calls(str(f))
    assert result == []


def test_extract_js_http_calls_axios_template_literal_reconstructed(tmp_path: pathlib.Path):
    # Template literals are reconstructed into a {param}-bearing path (spec v2-10)
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\naxios.get(`http://svc/users/${id}`);")
    result = extract_js_http_calls(str(f))
    assert result == [{"url": "/users/{param}", "file_path": str(f), "caller_function_name": None}]


def test_extract_js_http_calls_non_axios_lib_skipped(tmp_path: pathlib.Path):
    # Only "axios" as the object is matched — not other names
    f = tmp_path / "client.js"
    f.write_text('http.get("http://svc/path");')
    result = extract_js_http_calls(str(f))
    assert result == []


# ─── extract_js_http_calls: mixed / type checks ─────────────────────────────

def test_extract_js_http_calls_multiple_calls_all_captured(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text(
        'fetch("http://user-service/users/1");\n'
        'axios.get("http://payment-service/payments/2");\n'
        'axios.post("http://order-service/orders");\n'
    )
    result = extract_js_http_calls(str(f))
    urls = [c["url"] for c in result]
    assert "http://user-service/users/1" in urls
    assert "http://payment-service/payments/2" in urls
    assert "http://order-service/orders" in urls
    assert len(result) == 3


def test_extract_js_http_calls_returns_list_of_dicts(tmp_path: pathlib.Path):
    f = tmp_path / "client.js"
    f.write_text('fetch("http://svc/path");\naxios.get("http://svc/other");')
    result = extract_js_http_calls(str(f))
    assert isinstance(result, list)
    assert all(isinstance(c, dict) for c in result)
    assert all(isinstance(c["url"], str) for c in result)
    assert all(set(c.keys()) == {"url", "file_path", "caller_function_name"} for c in result)


def test_extract_js_http_calls_ts_file_parsed_correctly(tmp_path: pathlib.Path):
    # TypeScript files use the TS grammar but same call syntax is detected
    f = tmp_path / "client.ts"
    f.write_text('fetch("http://user-service/users/1");')
    result = extract_js_http_calls(str(f))
    assert "http://user-service/users/1" in [c["url"] for c in result]


def test_extract_js_http_calls_tsx_file_parsed_correctly(tmp_path: pathlib.Path):
    f = tmp_path / "client.tsx"
    f.write_text('axios.get("http://svc/data");')
    result = extract_js_http_calls(str(f))
    assert "http://svc/data" in [c["url"] for c in result]


def test_extract_js_http_calls_no_http_calls_returns_empty(tmp_path: pathlib.Path):
    f = tmp_path / "utils.js"
    f.write_text("function add(a, b) { return a + b; }")
    result = extract_js_http_calls(str(f))
    assert result == []


def test_extract_js_http_calls_nonexistent_file_returns_empty():
    result = extract_js_http_calls("/does/not/exist/client.ts")
    assert result == []


def test_extract_js_http_calls_empty_file_returns_empty(tmp_path: pathlib.Path):
    f = tmp_path / "empty.js"
    f.write_text("")
    result = extract_js_http_calls(str(f))
    assert result == []


# ─── detect_service_language ─────────────────────────────────────────────────

def test_detect_service_language_python_from_py_file(tmp_path: pathlib.Path):
    (tmp_path / "main.py").write_text("print('hello')")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_service_language_javascript_from_js_file(tmp_path: pathlib.Path):
    (tmp_path / "index.js").write_text("console.log('hello')")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_service_language_javascript_from_jsx_file(tmp_path: pathlib.Path):
    (tmp_path / "app.jsx").write_text("export default function App() { return null; }")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_service_language_javascript_from_ts_file(tmp_path: pathlib.Path):
    (tmp_path / "server.ts").write_text("const x: number = 1;")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_service_language_javascript_from_tsx_file(tmp_path: pathlib.Path):
    (tmp_path / "component.tsx").write_text("export default function C() { return null; }")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_service_language_unknown_when_empty(tmp_path: pathlib.Path):
    assert detect_service_language(str(tmp_path)) == "unknown"


def test_detect_service_language_unknown_with_unrecognized_extensions(tmp_path: pathlib.Path):
    (tmp_path / "README.md").write_text("# hello")
    (tmp_path / "config.yaml").write_text("key: value")
    assert detect_service_language(str(tmp_path)) == "unknown"


def test_detect_service_language_python_wins_over_js(tmp_path: pathlib.Path):
    # Both .py and .js are present — Python must take priority
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "index.js").write_text("console.log('hello')")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_service_language_python_wins_over_ts(tmp_path: pathlib.Path):
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "server.ts").write_text("const x = 1;")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_service_language_python_wins_over_tsx(tmp_path: pathlib.Path):
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "component.tsx").write_text("export default function C() {}")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_service_language_nested_py_file_detected(tmp_path: pathlib.Path):
    # .py file inside a subdirectory — os.walk finds it
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "utils.py").write_text("pass")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_service_language_nested_js_file_detected(tmp_path: pathlib.Path):
    # .js inside a subdirectory, no .py anywhere → "javascript"
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "utils.js").write_text("exports.fn = () => {};")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_service_language_returns_string(tmp_path: pathlib.Path):
    result = detect_service_language(str(tmp_path))
    assert isinstance(result, str)


def test_detect_service_language_result_is_one_of_three_values(tmp_path: pathlib.Path):
    (tmp_path / "index.js").write_text("const x = 1;")
    result = detect_service_language(str(tmp_path))
    assert result in {"python", "javascript", "unknown"}


# ─── _is_in_ignored_dir ──────────────────────────────────────────────────────
# This is a pure function in routers/analyze.py — no DB or IO needed.
# Path strings are built from tmp_path but files don't need to exist.

def test_is_in_ignored_dir_node_modules_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "node_modules" / "lib" / "index.js")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_git_dir_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / ".git" / "COMMIT_EDITMSG")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_venv_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / ".venv" / "lib" / "site.py")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_pycache_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "__pycache__" / "main.cpython-311.pyc")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_dist_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "dist" / "bundle.js")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_build_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "build" / "output.js")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_next_dir_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / ".next" / "server" / "chunks" / "page.js")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_coverage_returns_true(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "coverage" / "lcov-report" / "index.html")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_normal_subdir_returns_false(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "src" / "index.js")
    assert _is_in_ignored_dir(file_path, root) is False


def test_is_in_ignored_dir_file_directly_in_root_returns_false(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "main.py")
    assert _is_in_ignored_dir(file_path, root) is False


def test_is_in_ignored_dir_deeply_nested_ignored_dir_returns_true(tmp_path: pathlib.Path):
    # node_modules nested two levels below root must still be caught
    root = str(tmp_path)
    file_path = str(tmp_path / "packages" / "node_modules" / "react" / "index.js")
    assert _is_in_ignored_dir(file_path, root) is True


def test_is_in_ignored_dir_similar_but_not_ignored_name_returns_false(tmp_path: pathlib.Path):
    # "node_module" (singular) is NOT in IGNORED_DIRS
    root = str(tmp_path)
    file_path = str(tmp_path / "node_module" / "index.js")
    assert _is_in_ignored_dir(file_path, root) is False


def test_is_in_ignored_dir_returns_bool_not_just_truthy(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_in_ignored = str(tmp_path / "node_modules" / "x.js")
    file_in_normal = str(tmp_path / "src" / "x.js")
    assert _is_in_ignored_dir(file_in_ignored, root) is True
    assert _is_in_ignored_dir(file_in_normal, root) is False


def test_is_in_ignored_dir_deeply_nested_normal_dir_returns_false(tmp_path: pathlib.Path):
    root = str(tmp_path)
    file_path = str(tmp_path / "services" / "user" / "handlers" / "get.py")
    assert _is_in_ignored_dir(file_path, root) is False
