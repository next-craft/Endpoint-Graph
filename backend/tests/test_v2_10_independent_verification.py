# Independent cross-check for spec v2-10 (template literal & f-string URL detection),
# updated for spec v2-11's caller_function_name/file_path additions.
#
# These test cases were derived directly from .claude/specs/v2-10-template-literals.md
# and first-principles reasoning about tree-sitter parsing of JS template_string nodes
# and Python f-string (string) nodes -- NOT copied from the implementer's own test file
# (backend/tests/test_code_parser.py), which was deliberately not read while writing this.

from analysis.code_parser import extract_http_calls, extract_js_http_calls


# ---------------------------------------------------------------------------
# JS / TS: extract_js_http_calls
# ---------------------------------------------------------------------------

def test_js_fetch_template_env_host_static_path(tmp_path):
    # Dynamic host, static path -> reconstructed pattern "{param}/users" has no
    # "://", so the first "/" (index 7) marks the path start.
    src = "const API_HOST = process.env.API_HOST;\nfetch(`${API_HOST}/users`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/users", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_dynamic_path_segment(tmp_path):
    src = "const id = 1;\nfetch(`/users/${id}`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/users/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_axios_get_template_literal(tmp_path):
    src = "const id = 1;\naxios.get(`http://svc/users/${id}`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    result = extract_js_http_calls(str(f))
    assert "/users/{param}" in [c["url"] for c in result]


def test_js_axios_post_template_literal_other_method(tmp_path):
    # Confirms the axios template query isn't hardcoded to .get -- post/put/delete
    # must also match per the spec's method allow-list {"get", "post", "put", "delete"}.
    src = "const id = 1;\naxios.post(`http://svc/orders/${id}`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/orders/{param}", "method": "POST", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_multiple_substitutions(tmp_path):
    src = (
        "const id = 1;\n"
        "const orderId = 2;\n"
        "fetch(`/users/${id}/orders/${orderId}`);\n"
    )
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/users/{param}/orders/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_no_substitutions(tmp_path):
    # A template literal with zero ${} substitutions must still be matched by the
    # new template_string queries (not just ones containing dynamic segments).
    src = "fetch(`/users`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/users", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_template_no_path_at_all_excluded(tmp_path):
    # Reconstructed pattern is just "{param}" (host only) -- no "/" anywhere,
    # so _extract_path_from_pattern returns None and the call is dropped entirely.
    src = "const API_HOST = 'svc';\nfetch(`${API_HOST}`);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == []


def test_ts_fetch_template_literal_parity(tmp_path):
    # Same source, .ts extension -- confirms the TS grammar parses template_string
    # the same way as the JS grammar.
    src = "const id = 1;\nfetch(`http://svc/users/${id}`);\n"
    f = tmp_path / "client.ts"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "/users/{param}", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_plain_string_unaffected(tmp_path):
    # Sanity check: a plain (non-template) string literal call must still return
    # the full URL unchanged -- this feature must not regress existing behavior.
    src = "fetch('http://svc/users/1');\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == [
        {"url": "http://svc/users/1", "method": "GET", "file_path": str(f), "caller_function_name": None}
    ]


def test_js_fetch_variable_url_still_skipped(tmp_path):
    # Sanity check: a bare variable reference (not a literal of any kind) is
    # still excluded -- this spec only reconstructs template literals/f-strings.
    src = "const url = '/users';\nfetch(url);\n"
    f = tmp_path / "client.js"
    f.write_text(src)
    assert extract_js_http_calls(str(f)) == []


# ---------------------------------------------------------------------------
# Python: extract_http_calls
# ---------------------------------------------------------------------------

def test_requests_get_fstring_host(tmp_path):
    src = (
        "import requests\n"
        "HOST = 'svc'\n"
        "resp = requests.get(f\"http://{HOST}/users\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == [{"url": "/users", "method": "GET", "caller_function_name": None}]


def test_requests_get_fstring_path_segment(tmp_path):
    src = (
        "import requests\n"
        "user_id = 1\n"
        "resp = requests.get(f\"http://svc/users/{user_id}\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == [{"url": "/users/{param}", "method": "GET", "caller_function_name": None}]


def test_requests_get_fstring_multiple_substitutions(tmp_path):
    src = (
        "import requests\n"
        "user_id = 1\n"
        "order_id = 2\n"
        "resp = requests.get(f\"http://svc/users/{user_id}/orders/{order_id}\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == [
        {"url": "/users/{param}/orders/{param}", "method": "GET", "caller_function_name": None}
    ]


def test_requests_get_fstring_no_path_skipped(tmp_path):
    src = (
        "import requests\n"
        "HOST = 'svc'\n"
        "resp = requests.get(f\"http://{HOST}\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == []


def test_httpx_get_fstring_reconstructed(tmp_path):
    # Confirms reconstruction also applies to httpx, not just requests.
    src = (
        "import httpx\n"
        "order_id = 5\n"
        "resp = httpx.get(f\"http://svc/orders/{order_id}\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == [{"url": "/orders/{param}", "method": "GET", "caller_function_name": None}]


def test_requests_get_plain_string_unaffected(tmp_path):
    # Sanity check: a plain (non-f-string) string literal call is unaffected --
    # full URL returned unchanged, same as before this spec.
    src = (
        "import requests\n"
        "resp = requests.get(\"http://svc/users/1\")\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == [{"url": "http://svc/users/1", "method": "GET", "caller_function_name": None}]


def test_requests_get_variable_url_still_skipped(tmp_path):
    # Sanity check: a bare variable reference (not a literal/f-string) is still
    # excluded -- out of scope for this spec.
    src = (
        "import requests\n"
        "url = 'http://svc/users/1'\n"
        "resp = requests.get(url)\n"
    )
    f = tmp_path / "client.py"
    f.write_text(src)
    assert extract_http_calls(str(f)) == []
