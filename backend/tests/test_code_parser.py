import pytest
from analysis.code_parser import (
    extract_route_decorators,
    extract_http_calls,
    extract_js_routes,
    extract_js_http_calls,
    extract_router_local_prefix,
    extract_include_router_mounts,
    compose_route_path,
    file_exports_axios_instance,
    extract_default_imports,
    detect_service_language,
)


# ── extract_route_decorators ───────────────────────────────────────────────────

def test_extract_get_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.get("/users/{id}")\ndef get_user(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "GET", "path": "/users/{id}", "function_name": "get_user"}
    ]


def test_extract_post_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.post("/orders")\ndef create_order(): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "POST", "path": "/orders", "function_name": "create_order"}
    ]


def test_extract_put_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.put("/items/{id}")\ndef update_item(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "PUT", "path": "/items/{id}", "function_name": "update_item"}
    ]


def test_extract_delete_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.delete("/users/{id}")\ndef delete_user(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "DELETE", "path": "/users/{id}", "function_name": "delete_user"}
    ]


def test_extract_patch_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.patch("/tasks/{id}")\ndef patch_task(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "PATCH", "path": "/tasks/{id}", "function_name": "patch_task"}
    ]


def test_extract_router_prefix(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@router.get("/payments/{id}")\ndef get_payment(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [
        {"method": "GET", "path": "/payments/{id}", "function_name": "get_payment"}
    ]


def test_extract_multiple_decorators(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text(
        '@app.get("/users/{id}")\ndef get_user(id: int): ...\n\n'
        '@router.post("/orders")\ndef create_order(): ...\n\n'
        '@app.delete("/items/{item_id}")\ndef delete_item(item_id: int): ...\n'
    )
    result = extract_route_decorators(str(f))
    assert len(result) == 3
    assert {"method": "GET", "path": "/users/{id}", "function_name": "get_user"} in result
    assert {"method": "POST", "path": "/orders", "function_name": "create_order"} in result
    assert {"method": "DELETE", "path": "/items/{item_id}", "function_name": "delete_item"} in result


def test_extract_no_decorators(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text("def plain_function():\n    return 42\n")
    assert extract_route_decorators(str(f)) == []


def test_extract_non_string_path(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('PATH_VAR = "/users/{id}"\n\n@app.get(PATH_VAR)\ndef get_user(): ...\n')
    assert extract_route_decorators(str(f)) == []


def test_extract_empty_file(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text("")
    assert extract_route_decorators(str(f)) == []


def test_extract_decorator_captures_function_name(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.get("/users/{id}")\ndef get_user(id: int): ...\n')
    result = extract_route_decorators(str(f))
    assert result[0]["function_name"] == "get_user"


def test_extract_decorator_async_function_name(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.post("/orders")\nasync def create_order(): ...\n')
    result = extract_route_decorators(str(f))
    assert result[0]["function_name"] == "create_order"


# ── extract_router_local_prefix / extract_include_router_mounts / compose_route_path ──
# Regression coverage for v2-open-issues.md Issue 9: APIRouter(prefix=...) and
# include_router(..., prefix=...) were previously invisible to the parser, so a route
# declared as `@router.get("/{slug}")` under `APIRouter(prefix="/colleges")` mounted with
# `include_router(colleges.router, prefix="/v1")` was recorded as just "/{slug}" instead
# of "/v1/colleges/{slug}" -- both missing real matches and creating false ones (multiple
# distinct endpoints collapse to the same overly generic single-segment regex).

def test_extract_router_local_prefix_found(tmp_path):
    f = tmp_path / "colleges.py"
    f.write_text('router = APIRouter(prefix="/colleges", tags=["colleges"])\n')
    assert extract_router_local_prefix(str(f)) == "/colleges"


def test_extract_router_local_prefix_no_prefix_kwarg(tmp_path):
    f = tmp_path / "chat.py"
    f.write_text('router = APIRouter(tags=["conversations"])\n')
    assert extract_router_local_prefix(str(f)) is None


def test_extract_router_local_prefix_no_router_at_all(tmp_path):
    f = tmp_path / "plain.py"
    f.write_text('X = 42\n')
    assert extract_router_local_prefix(str(f)) is None


def test_extract_router_local_prefix_file_not_found():
    assert extract_router_local_prefix("/nonexistent/path/file.py") is None


def test_extract_include_router_mounts_attribute_ref(tmp_path):
    f = tmp_path / "main.py"
    f.write_text('app.include_router(colleges.router, prefix="/v1")\n')
    assert extract_include_router_mounts(str(f)) == [
        {"module_name": "colleges", "prefix": "/v1"}
    ]


def test_extract_include_router_mounts_multiple(tmp_path):
    f = tmp_path / "main.py"
    f.write_text(
        'app.include_router(colleges.router, prefix="/v1")\n'
        'app.include_router(users.router, prefix="/v1")\n'
    )
    result = extract_include_router_mounts(str(f))
    assert {"module_name": "colleges", "prefix": "/v1"} in result
    assert {"module_name": "users", "prefix": "/v1"} in result


def test_extract_include_router_mounts_bare_identifier_unresolved(tmp_path):
    f = tmp_path / "main.py"
    f.write_text('app.include_router(router, prefix="/v1")\n')
    assert extract_include_router_mounts(str(f)) == [
        {"module_name": None, "prefix": "/v1"}
    ]


def test_extract_include_router_mounts_no_prefix_kwarg(tmp_path):
    f = tmp_path / "main.py"
    f.write_text('app.include_router(colleges.router)\n')
    assert extract_include_router_mounts(str(f)) == []


def test_extract_include_router_mounts_no_calls(tmp_path):
    f = tmp_path / "main.py"
    f.write_text('X = 42\n')
    assert extract_include_router_mounts(str(f)) == []


def test_compose_route_path_mount_and_router_prefix_and_decorator_path():
    assert compose_route_path("/v1", "/colleges", "/{slug}") == "/v1/colleges/{slug}"


def test_compose_route_path_empty_decorator_path_is_the_prefix_root():
    # @router.get("") under APIRouter(prefix="/colleges") mounted at "/v1" -> "/v1/colleges"
    assert compose_route_path("/v1", "/colleges", "") == "/v1/colleges"


def test_compose_route_path_no_router_local_prefix():
    # chat.py has no APIRouter(prefix=...), only the include_router mount prefix applies
    assert compose_route_path("/v1", "", "/conversations") == "/v1/conversations"


def test_compose_route_path_no_prefixes_at_all():
    assert compose_route_path("", "", "/items") == "/items"


def test_compose_route_path_all_empty():
    assert compose_route_path("", "", "") == "/"


# ── extract_http_calls ─────────────────────────────────────────────────────────

def test_extract_requests_get(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.get("http://user-service/users/1")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://user-service/users/1", "method": "GET", "caller_function_name": None}
    ]


def test_extract_requests_post(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.post("http://payment-service/charge")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://payment-service/charge", "method": "POST", "caller_function_name": None}
    ]


def test_extract_httpx_get(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.get("http://user-service/users/profile")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://user-service/users/profile", "method": "GET", "caller_function_name": None}
    ]


def test_extract_httpx_post(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.post("http://order-service/orders")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://order-service/orders", "method": "POST", "caller_function_name": None}
    ]


def test_extract_requests_delete(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.delete("http://user-service/users/1")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://user-service/users/1", "method": "DELETE", "caller_function_name": None}
    ]


def test_extract_httpx_put(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.put("http://order-service/orders/42")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "http://order-service/orders/42", "method": "PUT", "caller_function_name": None}
    ]


def test_extract_multiple_calls(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\nimport httpx\n'
        'resp = requests.get("http://user-service/users/1")\n'
        'data = httpx.post("http://order-service/orders")\n'
    )
    result = extract_http_calls(str(f))
    assert len(result) == 2
    assert {"url": "http://user-service/users/1", "method": "GET", "caller_function_name": None} in result
    assert {"url": "http://order-service/orders", "method": "POST", "caller_function_name": None} in result


def test_extract_fstring_url_reconstructed(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nuser_id = 1\nresp = requests.get(f"http://svc/users/{user_id}")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "/users/{param}", "method": "GET", "caller_function_name": None}
    ]


def test_requests_get_fstring_host(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nHOST = "svc"\nresp = requests.get(f"http://{HOST}/users")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "/users", "method": "GET", "caller_function_name": None}
    ]


def test_requests_get_fstring_path_segment(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nuser_id = 1\nresp = requests.get(f"http://svc/users/{user_id}")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "/users/{param}", "method": "GET", "caller_function_name": None}
    ]


def test_requests_get_fstring_bare_host_resolves_to_root_path(tmp_path):
    # A bare-host f-string (no path segment at all) targets the root path "/",
    # not "no path" — the request is still made, just to "/".
    f = tmp_path / "client.py"
    f.write_text('import requests\nHOST = "svc"\nresp = requests.get(f"http://{HOST}")\n')
    assert extract_http_calls(str(f)) == [
        {"url": "/", "method": "GET", "caller_function_name": None}
    ]


def test_requests_get_fstring_multiple_substitutions(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\nuser_id = 1\norder_id = 2\n'
        'resp = requests.get(f"http://svc/users/{user_id}/orders/{order_id}")\n'
    )
    assert extract_http_calls(str(f)) == [
        {"url": "/users/{param}/orders/{param}", "method": "GET", "caller_function_name": None}
    ]


def test_extract_variable_url_skipped(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nurl_var = "http://svc/users/1"\nresp = requests.get(url_var)\n')
    assert extract_http_calls(str(f)) == []


def test_extract_no_http_calls(tmp_path):
    f = tmp_path / "client.py"
    f.write_text("def compute(x):\n    return x * 2\n")
    assert extract_http_calls(str(f)) == []


def test_extract_http_call_captures_caller_function_name(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\n\n'
        'def sync_user(id):\n'
        '    resp = requests.get("http://user-service/users/1")\n'
    )
    result = extract_http_calls(str(f))
    assert result == [
        {"url": "http://user-service/users/1", "method": "GET", "caller_function_name": "sync_user"}
    ]


def test_extract_http_call_module_scope_no_caller_function_name(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.get("http://user-service/users/1")\n')
    result = extract_http_calls(str(f))
    assert result == [
        {"url": "http://user-service/users/1", "method": "GET", "caller_function_name": None}
    ]


def test_extract_http_call_nested_function_caller_function_name(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\n\n'
        'def outer():\n'
        '    def inner():\n'
        '        resp = requests.get("http://user-service/users/1")\n'
        '    inner()\n'
    )
    result = extract_http_calls(str(f))
    assert result == [
        {"url": "http://user-service/users/1", "method": "GET", "caller_function_name": "inner"}
    ]


# ── error handling ─────────────────────────────────────────────────────────────

def test_extract_file_not_found():
    assert extract_route_decorators("/nonexistent/path/file.py") == []
    assert extract_http_calls("/nonexistent/path/file.py") == []


def test_extract_invalid_python(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n    pass\n")
    assert extract_route_decorators(str(f)) == []
    assert extract_http_calls(str(f)) == []


# ── extract_js_routes — Express ────────────────────────────────────────────────

def test_js_express_get(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("const handler = () => {};\napp.get('/users', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/users", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_post(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("router.post('/orders', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "POST", "path": "/orders", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_put(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.put('/items/:id', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "PUT", "path": "/items/:id", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_delete(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.delete('/users/:id', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "DELETE", "path": "/users/:id", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_patch(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.patch('/x', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "PATCH", "path": "/x", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_unknown_method(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.options('/x', handler);\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_express_template_literal_path_skipped(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("const id = 1;\napp.get(`/users/${id}`, h);\n")
    result = extract_js_routes(str(f))
    # template literals are template_string nodes and won't match (string) in the query
    assert result == []


def test_ts_express_route(tmp_path):
    f = tmp_path / "routes.ts"
    f.write_text("router.get('/payments/:id', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/payments/:id", "spec_source": "decorator_js", "function_name": "handler"} in result


def test_js_express_route_captures_handler_identifier(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("function getUser(req, res) {}\napp.get('/users', getUser);\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/users", "spec_source": "decorator_js", "function_name": "getUser"} in result


def test_js_express_route_arrow_handler_no_function_name(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/users', (req, res) => {});\n")
    result = extract_js_routes(str(f))
    assert result[0]["function_name"] is None


def test_js_express_route_anonymous_function_handler(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.get('/users', function (req, res) {});\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/users", "spec_source": "decorator_js", "function_name": None} in result


# ── extract_js_routes — Issue 11: no handler arg must not fabricate a route ────

def test_js_single_arg_get_call_on_bare_object_not_a_route(tmp_path):
    """`api.get(url)` — a wrapped axios instance HTTP call, not an Express route
    declaration — must not be mistaken for one just because the method name and a
    lone string argument happen to match the Express shape."""
    f = tmp_path / "queries.js"
    f.write_text("async function useMe() { return (await api.get('/users/me')).data; }\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_urlsearchparams_get_call_not_a_route(tmp_path):
    f = tmp_path / "utils.js"
    f.write_text("function readId(params) { return params.get('/id'); }\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_formdata_get_call_not_a_route(tmp_path):
    f = tmp_path / "utils.js"
    f.write_text("function readFile(fd) { return fd.get('/file'); }\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_get_call_with_non_handler_second_arg_not_a_route(tmp_path):
    """A second argument that isn't a function-like node (identifier / arrow /
    function expression) — e.g. a plain options object — still isn't a route."""
    f = tmp_path / "queries.js"
    f.write_text("api.get('/users/me', { timeout: 5000 });\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_wrapped_axios_call_with_identifier_data_arg_not_a_route(tmp_path):
    """`api.patch('/users/me', payload)` — a wrapped-axios HTTP call whose second
    arg happens to be a plain identifier (the data payload, not a handler) — is
    syntactically indistinguishable from `app.patch('/x', handler)` by node shape
    alone. Passing axios_identifiers (resolved by the caller from cross-file
    default-import tracing, same as Issue 10) is what disambiguates it."""
    f = tmp_path / "queries.js"
    f.write_text("const fn = (payload) => api.patch('/users/me', payload);\n")
    assert extract_js_routes(str(f), frozenset({"api"})) == []
    # Without knowing "api" is an axios instance, this shape is indistinguishable
    # from a real Express route and is still (correctly) treated as one.
    assert extract_js_routes(str(f), frozenset({"axios"})) != []


# ── extract_js_routes — Next.js ────────────────────────────────────────────────

def test_nextjs_get_route(tmp_path):
    route_dir = tmp_path / "app" / "api" / "users"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.js"
    f.write_text(
        "export async function GET(req) { return new Response('ok'); }\n"
        "export async function POST(req) { return new Response('created'); }\n"
    )
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/api/users", "spec_source": "nextjs_route", "function_name": "GET"} in result
    assert {"method": "POST", "path": "/api/users", "spec_source": "nextjs_route", "function_name": "POST"} in result


def test_nextjs_dynamic_route(tmp_path):
    route_dir = tmp_path / "app" / "api" / "users" / "[id]"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.js"
    f.write_text("export function GET(req) { return new Response('ok'); }\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/api/users/{id}", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_nextjs_catch_all_route(tmp_path):
    route_dir = tmp_path / "app" / "api" / "[...slug]"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.ts"
    f.write_text("export function GET() { return new Response('ok'); }\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/api/{slug}", "spec_source": "nextjs_route", "function_name": "GET"} in result


def test_nextjs_non_route_file_skipped(tmp_path):
    helpers_dir = tmp_path / "app" / "api" / "users"
    helpers_dir.mkdir(parents=True)
    f = helpers_dir / "helpers.js"
    f.write_text("export function helper() { return 42; }\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_nextjs_no_http_exports(tmp_path):
    route_dir = tmp_path / "app" / "api" / "users"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.js"
    f.write_text("export function helper() { return 42; }\n")
    result = extract_js_routes(str(f))
    assert result == []


def test_js_nextjs_route_function_name_equals_method(tmp_path):
    route_dir = tmp_path / "app" / "api" / "users"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.js"
    f.write_text(
        "export async function GET(req) { return new Response('ok'); }\n"
        "export async function POST(req) { return new Response('created'); }\n"
    )
    result = extract_js_routes(str(f))
    assert len(result) == 2
    for ep in result:
        assert ep["function_name"] == ep["method"]


# ── extract_js_http_calls ──────────────────────────────────────────────────────

def test_js_fetch_call(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('fetch("http://user-service/users/1");\n')
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://user-service/users/1", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_axios_get(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.get("http://svc/users/1");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/users/1" in [c["url"] for c in result]


def test_js_axios_post(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.post("http://svc/orders");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/orders" in [c["url"] for c in result]


def test_js_axios_delete(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.delete("http://svc/items/1");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/items/1" in [c["url"] for c in result]


def test_js_axios_patch(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.patch("http://svc/tasks/1");\n')
    result = extract_js_http_calls(str(f))
    assert {"url": "http://svc/tasks/1", "method": "PATCH"}.items() <= result[0].items()


def test_js_axios_patch_template_literal_matches_patch_endpoint(tmp_path):
    from analysis.url_matcher import match_url_to_endpoint

    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfunction updateTaskApi() { axios.patch(`/tasks/${id}`); }\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/tasks/{param}", "method": "PATCH", "file_path": str(f), "caller_function_name": "updateTaskApi"}
    ]
    assert match_url_to_endpoint(result[0]["url"], ["/tasks/{id}"]) == "/tasks/{id}"


def test_js_fetch_template_literal_reconstructed(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfetch(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_env_host_static_path(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}/users`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_dynamic_path_segment(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfetch(`/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_axios_get_template_literal(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\naxios.get(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert "/users/{param}" in [c["url"] for c in result]


def test_js_fetch_template_bare_host_resolves_to_root_path(tmp_path):
    # A bare-host template literal (no path segment at all) targets the root
    # path "/", not "no path" — the request is still made, just to "/".
    f = tmp_path / "client.js"
    f.write_text("const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_multiple_substitutions(tmp_path):
    f = tmp_path / "client.js"
    f.write_text(
        "const id = 1;\nconst orderId = 2;\n"
        "fetch(`/users/${id}/orders/${orderId}`);\n"
    )
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users/{param}/orders/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_no_substitutions(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("fetch(`/users`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_ts_fetch_template_literal(tmp_path):
    f = tmp_path / "client.ts"
    f.write_text("const id = 1;\nfetch(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/users/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_path_with_embedded_scheme_not_truncated(tmp_path):
    # The reconstructed pattern has no scheme of its own (starts with "/"), but
    # its path contains an embedded "://" (e.g. a redirect target). Scheme
    # detection must be anchored to the start of the pattern, not match this.
    f = tmp_path / "client.js"
    f.write_text("fetch(`/redirect?to=https://other/x`);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "/redirect?to=https://other/x", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_template_literal_invalid_utf8_does_not_blank_file(tmp_path):
    # A malformed byte sequence inside one template literal's static text must
    # not raise UnicodeDecodeError and wipe out other valid calls in the file.
    f = tmp_path / "client.js"
    f.write_bytes(
        b'fetch("http://user-service/users/1");\n'
        b"const id = 1;\n"
        b"fetch(`/users/" + b"\xff\xfe" + b"/${id}`);\n"
    )
    result = extract_js_http_calls(str(f))
    assert "http://user-service/users/1" in [c["url"] for c in result]


def test_js_fetch_variable_url_skipped(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('const url = "http://svc";\nfetch(url);\n')
    result = extract_js_http_calls(str(f))
    assert result == []


def test_js_multiple_http_calls(tmp_path):
    f = tmp_path / "client.js"
    f.write_text(
        'fetch("http://user-service/users/1");\n'
        'axios.get("http://order-service/orders");\n'
    )
    result = extract_js_http_calls(str(f))
    urls = [c["url"] for c in result]
    assert "http://user-service/users/1" in urls
    assert "http://order-service/orders" in urls


def test_ts_fetch_call(tmp_path):
    f = tmp_path / "client.ts"
    f.write_text('fetch("http://svc/path");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/path" in [c["url"] for c in result]


def test_js_http_calls_no_calls(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("function compute(x) { return x * 2; }\n")
    result = extract_js_http_calls(str(f))
    assert result == []


def test_js_http_call_captures_caller_function_name_declaration(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("function fetchUser() { fetch('http://svc/users/1'); }\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": "fetchUser"}
    ]


def test_js_http_call_captures_caller_function_name_named_arrow(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const fetchUser = () => { fetch('http://svc/users/1'); };\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": "fetchUser"}
    ]


def test_js_http_call_captures_caller_function_name_method_definition(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("class ApiClient { getUser() { fetch('http://svc/users/1'); } }\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": "getUser"}
    ]


def test_js_http_call_anonymous_arrow_no_caller_function_name(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("setTimeout(() => fetch('http://svc/users/1'), 100);\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_http_call_module_scope_no_caller_function_name(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("fetch('http://svc/users/1');\n")
    result = extract_js_http_calls(str(f))
    assert result == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_http_call_includes_file_path(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('fetch("http://user-service/users/1");\n')
    result = extract_js_http_calls(str(f))
    assert all(c["file_path"] == str(f) for c in result)


def test_js_routes_file_not_found():
    assert extract_js_routes("/nonexistent.js") == []


def test_js_http_calls_file_not_found():
    assert extract_js_http_calls("/nonexistent.ts") == []


# ── file_exports_axios_instance / extract_default_imports / axios_identifiers ──
# Regression coverage for v2-open-issues.md Issue 10: a wrapped axios client
# (`const api = axios.create(...); export default api`) was invisible to
# extract_js_http_calls -- only the literal identifier "axios" was ever recognized,
# so every `api.get(...)` call site (the standard pattern for centralizing baseURL +
# auth headers) was silently dropped.

def test_file_exports_axios_instance_true(tmp_path):
    f = tmp_path / "api.js"
    f.write_text(
        'import axios from "axios"\n'
        "const api = axios.create({ baseURL: X })\n"
        "export default api\n"
    )
    assert file_exports_axios_instance(str(f)) is True


def test_file_exports_axios_instance_not_default_exported(tmp_path):
    f = tmp_path / "api.js"
    f.write_text(
        'import axios from "axios"\n'
        "const api = axios.create({ baseURL: X })\n"
    )
    assert file_exports_axios_instance(str(f)) is False


def test_file_exports_axios_instance_no_axios_create(tmp_path):
    f = tmp_path / "thing.js"
    f.write_text(
        "const thing = makeThing()\n"
        "export default thing\n"
    )
    assert file_exports_axios_instance(str(f)) is False


def test_file_exports_axios_instance_exports_a_different_variable(tmp_path):
    f = tmp_path / "api.js"
    f.write_text(
        'import axios from "axios"\n'
        "const api = axios.create({ baseURL: X })\n"
        "const other = 42\n"
        "export default other\n"
    )
    assert file_exports_axios_instance(str(f)) is False


def test_file_exports_axios_instance_file_not_found():
    assert file_exports_axios_instance("/nonexistent.js") is False


def test_extract_default_imports_finds_local_name_and_source(tmp_path):
    f = tmp_path / "queries.js"
    f.write_text('import api from "@/lib/api"\n')
    assert extract_default_imports(str(f)) == [{"local_name": "api", "source": "@/lib/api"}]


def test_extract_default_imports_ignores_named_imports(tmp_path):
    f = tmp_path / "queries.js"
    f.write_text('import { useQuery } from "@tanstack/react-query"\n')
    assert extract_default_imports(str(f)) == []


def test_extract_default_imports_multiple(tmp_path):
    f = tmp_path / "queries.js"
    f.write_text(
        'import api from "@/lib/api"\n'
        'import motion from "@/lib/motion"\n'
    )
    result = extract_default_imports(str(f))
    assert {"local_name": "api", "source": "@/lib/api"} in result
    assert {"local_name": "motion", "source": "@/lib/motion"} in result


def test_extract_default_imports_file_not_found():
    assert extract_default_imports("/nonexistent.js") == []


def test_extract_js_http_calls_wrapped_axios_instance_recognized(tmp_path):
    # api.get(...) is only detected when "api" is explicitly passed as a known
    # axios identifier -- this simulates what analyze.py resolves cross-file.
    f = tmp_path / "queries.js"
    f.write_text('api.get("/users/me");\n')
    assert extract_js_http_calls(str(f)) == []
    assert extract_js_http_calls(str(f), frozenset({"axios", "api"})) == [
        {"url": "/users/me", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_extract_js_http_calls_wrapped_axios_instance_template_literal(tmp_path):
    f = tmp_path / "queries.js"
    f.write_text('api.get(`/listings/${id}`);\n')
    result = extract_js_http_calls(str(f), frozenset({"axios", "api"}))
    assert result == [
        {"url": "/listings/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


# ── detect_service_language ────────────────────────────────────────────────────

def test_detect_language_python(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')\n")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_language_javascript(tmp_path):
    (tmp_path / "index.js").write_text("console.log('hello');\n")
    assert detect_service_language(str(tmp_path)) == "javascript"


def test_detect_language_unknown(tmp_path):
    assert detect_service_language(str(tmp_path)) == "unknown"


def test_detect_language_python_wins(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "index.js").write_text("console.log('hello');\n")
    assert detect_service_language(str(tmp_path)) == "python"


def test_detect_language_ts_counts_as_javascript(tmp_path):
    (tmp_path / "server.ts").write_text("console.log('hello');\n")
    assert detect_service_language(str(tmp_path)) == "javascript"
