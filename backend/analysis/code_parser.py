import ast
import os
import re
from tree_sitter_languages import get_language, get_parser

PY_LANGUAGE = get_language("python")
parser = get_parser("python")

JS_LANGUAGE = get_language("javascript")
TS_LANGUAGE = get_language("typescript")
js_parser = get_parser("javascript")
ts_parser = get_parser("typescript")

DECORATOR_QUERY = PY_LANGUAGE.query("""
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier)
        attribute: (identifier) @method)
      arguments: (argument_list
        (string) @path))))
""")

HTTP_CALL_QUERY = PY_LANGUAGE.query("""
(call
  function: (attribute
    object: (identifier) @lib
    attribute: (identifier) @method)
  arguments: (argument_list
    (string) @url))
""")

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _is_fstring(node) -> bool:
    raw = node.text.decode("utf-8")
    return raw.startswith(("f'", 'f"', "F'", 'F"'))


def _safe_decode(raw: bytes) -> str:
    # Isolates decode failures to the one fragment being decoded, mirroring
    # _node_string_value's try/except — one malformed byte sequence in a
    # single call site must not blank out every other call already found
    # in the file via the caller's blanket `except Exception: return []`.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _extract_path_from_pattern(pattern: str) -> str | None:
    # If the pattern starts with a scheme (http://, {param}:// is not valid
    # here since a scheme is always static), skip past "://" and any host
    # segment (static or "{param}") so the search lands on the real path
    # instead of matching the "//" that follows the scheme.
    match = _SCHEME_RE.match(pattern)
    search_from = match.end() if match else 0
    slash_idx = pattern.find("/", search_from)
    if slash_idx == -1:
        return None  # no path at all (e.g. a bare host) — caller must skip this result
    return pattern[slash_idx:]


def _reconstruct_template_string(node, source: bytes) -> str:
    # Unlike Python f-strings (see _reconstruct_fstring), literal text between
    # ${...} substitutions is NOT exposed as its own child node in this pinned
    # grammar — it must be sliced directly out of the raw source bytes by
    # offset instead of read off a node via `.text`.
    parts = []
    cursor = node.start_byte + 1  # skip opening backtick
    end = node.end_byte - 1  # exclude closing backtick
    for child in node.children:
        if child.type == "template_substitution":
            if child.start_byte > cursor:
                parts.append(_safe_decode(source[cursor:child.start_byte]))
            parts.append("{param}")
            cursor = child.end_byte
    if cursor < end:
        parts.append(_safe_decode(source[cursor:end]))
    return "".join(parts)


def _reconstruct_fstring(node) -> str:
    parts = []
    for child in node.children:
        if child.type == "string_content":
            parts.append(_safe_decode(child.text))
        elif child.type == "interpolation":
            parts.append("{param}")
    return "".join(parts)


def _node_string_value(node) -> str | None:
    raw = node.text.decode("utf-8")
    try:
        return ast.literal_eval(raw)
    except Exception:
        return None


def _get_js_parser(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".ts", ".tsx"}:
        return TS_LANGUAGE, ts_parser
    return JS_LANGUAGE, js_parser


def _nextjs_api_path(file_path: str) -> str | None:
    normalized = file_path.replace("\\", "/")
    marker = "/app/"
    idx = normalized.find(marker)
    if idx == -1:
        return None
    after = normalized[idx + len(marker):]
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
    after = re.sub(r"\[\.\.\.([^\]]+)\]", r"{\1}", after)
    after = re.sub(r"\[([^\]]+)\]", r"{\1}", after)
    return "/" + after if after else "/"


def extract_route_decorators(file_path: str) -> list[dict]:
    try:
        source = open(file_path, "rb").read()
        tree = parser.parse(source)
        results = []
        for _, match in DECORATOR_QUERY.matches(tree.root_node):
            method_node = match.get("method")
            path_node = match.get("path")
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
            results.append({"method": method_text, "path": path_value})
        return results
    except Exception:
        return []


def extract_http_calls(file_path: str) -> list[dict]:
    try:
        source = open(file_path, "rb").read()
        tree = parser.parse(source)
        results = []
        for _, match in HTTP_CALL_QUERY.matches(tree.root_node):
            lib_node = match.get("lib")
            method_node = match.get("method")
            url_node = match.get("url")
            if lib_node is None or method_node is None or url_node is None:
                continue
            lib_text = lib_node.text.decode("utf-8")
            if lib_text not in {"requests", "httpx"}:
                continue
            method_text = method_node.text.decode("utf-8")
            if method_text not in {"get", "post", "put", "delete"}:
                continue
            if _is_fstring(url_node):
                pattern = _reconstruct_fstring(url_node)
                path = _extract_path_from_pattern(pattern)
                if path is None:
                    continue
                results.append({"url": path})
                continue
            url_value = _node_string_value(url_node)
            if url_value is None:
                continue
            results.append({"url": url_value})
        return results
    except Exception:
        return []


def extract_js_routes(file_path: str) -> list[dict]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        results = []

        # Case A — Express-style route declarations
        # Matches any object method call whose method is get/post/put/delete and
        # whose first argument is a string literal. This is intentionally broad —
        # Express apps use arbitrary variable names (app, router, api, v1, etc.)
        # so restricting by object name would miss valid routes.
        express_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier)
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path))
""")
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
            results.append({"method": method, "path": path_value, "spec_source": "decorator_js"})

        # Case B — Next.js App Router file-based routes
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


def _is_fetch_call(match) -> bool:
    fn_node = match.get("fn")
    return fn_node is not None and fn_node.text.decode("utf-8") == "fetch"


def _is_axios_call(match) -> bool:
    lib_node = match.get("lib")
    method_node = match.get("method")
    if lib_node is None or method_node is None:
        return False
    if lib_node.text.decode("utf-8") != "axios":
        return False
    return method_node.text.decode("utf-8") in {"get", "post", "put", "delete"}


def _resolve_plain_string_url(url_node) -> str | None:
    raw = url_node.text.decode("utf-8")
    if raw.startswith("`"):
        return None
    try:
        url = ast.literal_eval(raw)
    except Exception:
        return None
    return url if isinstance(url, str) else None


def _resolve_template_url(url_node, source: bytes) -> str | None:
    pattern = _reconstruct_template_string(url_node, source)
    return _extract_path_from_pattern(pattern)


def _collect_js_calls(query, tree_root, is_valid_call, resolve_url) -> list[str]:
    out = []
    for _, match in query.matches(tree_root):
        url_node = match.get("url")
        if url_node is None or not is_valid_call(match):
            continue
        url = resolve_url(url_node)
        if url is not None:
            out.append(url)
    return out


def extract_js_http_calls(file_path: str) -> list[str]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        root = tree.root_node
        results = []

        # fetch("url")
        fetch_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (string) @url))
""")
        results += _collect_js_calls(fetch_query, root, _is_fetch_call, _resolve_plain_string_url)

        # axios.get/post/put/delete("url")
        axios_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @url))
""")
        results += _collect_js_calls(axios_query, root, _is_axios_call, _resolve_plain_string_url)

        # fetch(`template literal`)
        fetch_template_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (template_string) @url))
""")
        results += _collect_js_calls(
            fetch_template_query, root, _is_fetch_call,
            lambda url_node: _resolve_template_url(url_node, source),
        )

        # axios.get/post/put/delete(`template literal`)
        axios_template_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (template_string) @url))
""")
        results += _collect_js_calls(
            axios_template_query, root, _is_axios_call,
            lambda url_node: _resolve_template_url(url_node, source),
        )

        return results
    except Exception:
        return []


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
