import pytest
from analysis.code_parser import (
    extract_route_decorators,
    extract_http_calls,
    extract_js_routes,
    extract_js_http_calls,
    detect_service_language,
)


# ── extract_route_decorators ───────────────────────────────────────────────────

def test_extract_get_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.get("/users/{id}")\ndef get_user(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [{"method": "GET", "path": "/users/{id}"}]


def test_extract_post_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.post("/orders")\ndef create_order(): ...\n')
    assert extract_route_decorators(str(f)) == [{"method": "POST", "path": "/orders"}]


def test_extract_put_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.put("/items/{id}")\ndef update_item(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [{"method": "PUT", "path": "/items/{id}"}]


def test_extract_delete_decorator(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@app.delete("/users/{id}")\ndef delete_user(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [{"method": "DELETE", "path": "/users/{id}"}]


def test_extract_router_prefix(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text('@router.get("/payments/{id}")\ndef get_payment(id: int): ...\n')
    assert extract_route_decorators(str(f)) == [{"method": "GET", "path": "/payments/{id}"}]


def test_extract_multiple_decorators(tmp_path):
    f = tmp_path / "routes.py"
    f.write_text(
        '@app.get("/users/{id}")\ndef get_user(id: int): ...\n\n'
        '@router.post("/orders")\ndef create_order(): ...\n\n'
        '@app.delete("/items/{item_id}")\ndef delete_item(item_id: int): ...\n'
    )
    result = extract_route_decorators(str(f))
    assert len(result) == 3
    assert {"method": "GET", "path": "/users/{id}"} in result
    assert {"method": "POST", "path": "/orders"} in result
    assert {"method": "DELETE", "path": "/items/{item_id}"} in result


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


# ── extract_http_calls ─────────────────────────────────────────────────────────

def test_extract_requests_get(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.get("http://user-service/users/1")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://user-service/users/1"}]


def test_extract_requests_post(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.post("http://payment-service/charge")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://payment-service/charge"}]


def test_extract_httpx_get(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.get("http://user-service/users/profile")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://user-service/users/profile"}]


def test_extract_httpx_post(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.post("http://order-service/orders")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://order-service/orders"}]


def test_extract_requests_delete(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nresp = requests.delete("http://user-service/users/1")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://user-service/users/1"}]


def test_extract_httpx_put(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import httpx\ndata = httpx.put("http://order-service/orders/42")\n')
    assert extract_http_calls(str(f)) == [{"url": "http://order-service/orders/42"}]


def test_extract_multiple_calls(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\nimport httpx\n'
        'resp = requests.get("http://user-service/users/1")\n'
        'data = httpx.post("http://order-service/orders")\n'
    )
    result = extract_http_calls(str(f))
    assert len(result) == 2
    assert {"url": "http://user-service/users/1"} in result
    assert {"url": "http://order-service/orders"} in result


def test_extract_fstring_url_reconstructed(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nuser_id = 1\nresp = requests.get(f"http://svc/users/{user_id}")\n')
    assert extract_http_calls(str(f)) == [{"url": "/users/{param}"}]


def test_requests_get_fstring_host(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nHOST = "svc"\nresp = requests.get(f"http://{HOST}/users")\n')
    assert extract_http_calls(str(f)) == [{"url": "/users"}]


def test_requests_get_fstring_path_segment(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nuser_id = 1\nresp = requests.get(f"http://svc/users/{user_id}")\n')
    assert extract_http_calls(str(f)) == [{"url": "/users/{param}"}]


def test_requests_get_fstring_no_path_skipped(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nHOST = "svc"\nresp = requests.get(f"http://{HOST}")\n')
    assert extract_http_calls(str(f)) == []


def test_requests_get_fstring_multiple_substitutions(tmp_path):
    f = tmp_path / "client.py"
    f.write_text(
        'import requests\nuser_id = 1\norder_id = 2\n'
        'resp = requests.get(f"http://svc/users/{user_id}/orders/{order_id}")\n'
    )
    assert extract_http_calls(str(f)) == [{"url": "/users/{param}/orders/{param}"}]


def test_extract_variable_url_skipped(tmp_path):
    f = tmp_path / "client.py"
    f.write_text('import requests\nurl_var = "http://svc/users/1"\nresp = requests.get(url_var)\n')
    assert extract_http_calls(str(f)) == []


def test_extract_no_http_calls(tmp_path):
    f = tmp_path / "client.py"
    f.write_text("def compute(x):\n    return x * 2\n")
    assert extract_http_calls(str(f)) == []


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
    assert {"method": "GET", "path": "/users", "spec_source": "decorator_js"} in result


def test_js_express_post(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("router.post('/orders', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "POST", "path": "/orders", "spec_source": "decorator_js"} in result


def test_js_express_put(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.put('/items/:id', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "PUT", "path": "/items/:id", "spec_source": "decorator_js"} in result


def test_js_express_delete(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.delete('/users/:id', handler);\n")
    result = extract_js_routes(str(f))
    assert {"method": "DELETE", "path": "/users/:id", "spec_source": "decorator_js"} in result


def test_js_express_unknown_method(tmp_path):
    f = tmp_path / "routes.js"
    f.write_text("app.patch('/x', handler);\n")
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
    assert {"method": "GET", "path": "/payments/:id", "spec_source": "decorator_js"} in result


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
    assert {"method": "GET", "path": "/api/users", "spec_source": "nextjs_route"} in result
    assert {"method": "POST", "path": "/api/users", "spec_source": "nextjs_route"} in result


def test_nextjs_dynamic_route(tmp_path):
    route_dir = tmp_path / "app" / "api" / "users" / "[id]"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.js"
    f.write_text("export function GET(req) { return new Response('ok'); }\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/api/users/{id}", "spec_source": "nextjs_route"} in result


def test_nextjs_catch_all_route(tmp_path):
    route_dir = tmp_path / "app" / "api" / "[...slug]"
    route_dir.mkdir(parents=True)
    f = route_dir / "route.ts"
    f.write_text("export function GET() { return new Response('ok'); }\n")
    result = extract_js_routes(str(f))
    assert {"method": "GET", "path": "/api/{slug}", "spec_source": "nextjs_route"} in result


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


# ── extract_js_http_calls ──────────────────────────────────────────────────────

def test_js_fetch_call(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('fetch("http://user-service/users/1");\n')
    result = extract_js_http_calls(str(f))
    assert result == ["http://user-service/users/1"]


def test_js_axios_get(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.get("http://svc/users/1");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/users/1" in result


def test_js_axios_post(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.post("http://svc/orders");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/orders" in result


def test_js_axios_delete(tmp_path):
    f = tmp_path / "client.js"
    f.write_text('axios.delete("http://svc/items/1");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/items/1" in result


def test_js_fetch_template_literal_reconstructed(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfetch(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/users/{param}"]


def test_js_fetch_template_env_host_static_path(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}/users`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/users"]


def test_js_fetch_template_dynamic_path_segment(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\nfetch(`/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/users/{param}"]


def test_js_axios_get_template_literal(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const id = 1;\naxios.get(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert "/users/{param}" in result


def test_js_fetch_template_no_path_skipped(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == []


def test_js_fetch_template_multiple_substitutions(tmp_path):
    f = tmp_path / "client.js"
    f.write_text(
        "const id = 1;\nconst orderId = 2;\n"
        "fetch(`/users/${id}/orders/${orderId}`);\n"
    )
    result = extract_js_http_calls(str(f))
    assert result == ["/users/{param}/orders/{param}"]


def test_js_fetch_template_no_substitutions(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("fetch(`/users`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/users"]


def test_ts_fetch_template_literal(tmp_path):
    f = tmp_path / "client.ts"
    f.write_text("const id = 1;\nfetch(`http://svc/users/${id}`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/users/{param}"]


def test_js_fetch_template_path_with_embedded_scheme_not_truncated(tmp_path):
    # The reconstructed pattern has no scheme of its own (starts with "/"), but
    # its path contains an embedded "://" (e.g. a redirect target). Scheme
    # detection must be anchored to the start of the pattern, not match this.
    f = tmp_path / "client.js"
    f.write_text("fetch(`/redirect?to=https://other/x`);\n")
    result = extract_js_http_calls(str(f))
    assert result == ["/redirect?to=https://other/x"]


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
    assert "http://user-service/users/1" in result


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
    assert "http://user-service/users/1" in result
    assert "http://order-service/orders" in result


def test_ts_fetch_call(tmp_path):
    f = tmp_path / "client.ts"
    f.write_text('fetch("http://svc/path");\n')
    result = extract_js_http_calls(str(f))
    assert "http://svc/path" in result


def test_js_http_calls_no_calls(tmp_path):
    f = tmp_path / "client.js"
    f.write_text("function compute(x) { return x * 2; }\n")
    result = extract_js_http_calls(str(f))
    assert result == []


def test_js_routes_file_not_found():
    assert extract_js_routes("/nonexistent.js") == []


def test_js_http_calls_file_not_found():
    assert extract_js_http_calls("/nonexistent.ts") == []


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
