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
        (string) @path)))
  definition: (function_definition
    name: (identifier) @function_name))
""")

HTTP_CALL_QUERY = PY_LANGUAGE.query("""
(call
  function: (attribute
    object: (identifier) @lib
    attribute: (identifier) @method)
  arguments: (argument_list
    (string) @url))
""")

ROUTER_PREFIX_QUERY = PY_LANGUAGE.query("""
(assignment
  right: (call
    function: (identifier) @callee
    arguments: (argument_list
      (keyword_argument
        name: (identifier) @kwname
        value: (string) @kwvalue))))
""")

INCLUDE_ROUTER_QUERY = PY_LANGUAGE.query("""
(call
  function: (attribute
    attribute: (identifier) @method)
  arguments: (argument_list
    . (_) @router_ref
    (keyword_argument
      name: (identifier) @kwname
      value: (string) @kwvalue)))
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
            function_name_node = match.get("function_name")
            if method_node is None or path_node is None:
                continue
            method_text = method_node.text.decode("utf-8").upper()
            if method_text not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if _is_fstring(path_node):
                continue
            path_value = _node_string_value(path_node)
            if path_value is None:
                continue
            function_name = function_name_node.text.decode("utf-8") if function_name_node is not None else None
            results.append({"method": method_text, "path": path_value, "function_name": function_name})
        return results
    except Exception:
        return []


def extract_router_local_prefix(file_path: str) -> str | None:
    """Return the prefix passed to `<var> = APIRouter(prefix="...")` in this file, if any.

    A decorator's own path (e.g. `@router.get("/{slug}")`) is only the suffix mounted
    under this router-level prefix -- without it, `/colleges/{slug}` gets recorded as
    just `/{slug}`, which degrades to an overly generic single-segment regex in
    url_matcher and both misses real matches and creates false ones."""
    try:
        source = open(file_path, "rb").read()
        tree = parser.parse(source)
        for _, match in ROUTER_PREFIX_QUERY.matches(tree.root_node):
            callee_node = match.get("callee")
            kwname_node = match.get("kwname")
            kwvalue_node = match.get("kwvalue")
            if callee_node is None or kwname_node is None or kwvalue_node is None:
                continue
            if callee_node.text.decode("utf-8") != "APIRouter":
                continue
            if kwname_node.text.decode("utf-8") != "prefix":
                continue
            value = _node_string_value(kwvalue_node)
            if value:
                return value
        return None
    except Exception:
        return None


def extract_include_router_mounts(file_path: str) -> list[dict]:
    """Return the mount prefix of every `<app>.include_router(<ref>, prefix="...")` call
    in this file, alongside the module name `<ref>` was accessed through when it's an
    attribute access (e.g. `colleges.router` -> module_name="colleges"). A bare
    identifier ref (no import tracing) yields module_name=None and is left unresolved."""
    try:
        source = open(file_path, "rb").read()
        tree = parser.parse(source)
        results = []
        for _, match in INCLUDE_ROUTER_QUERY.matches(tree.root_node):
            method_node = match.get("method")
            router_ref_node = match.get("router_ref")
            kwname_node = match.get("kwname")
            kwvalue_node = match.get("kwvalue")
            if method_node is None or router_ref_node is None or kwname_node is None or kwvalue_node is None:
                continue
            if method_node.text.decode("utf-8") != "include_router":
                continue
            if kwname_node.text.decode("utf-8") != "prefix":
                continue
            prefix_value = _node_string_value(kwvalue_node)
            if prefix_value is None:
                continue
            module_name = None
            if router_ref_node.type == "attribute":
                obj_node = router_ref_node.child_by_field_name("object")
                if obj_node is not None and obj_node.type == "identifier":
                    module_name = obj_node.text.decode("utf-8")
            results.append({"module_name": module_name, "prefix": prefix_value})
        return results
    except Exception:
        return []


def compose_route_path(*parts: str) -> str:
    """Join API path fragments (mount prefix, router-local prefix, decorator path) into
    one normalized path. Each fragment may be '', '/', or '/things' -- an empty decorator
    path (e.g. `@router.get("")`, FastAPI's way of exposing the prefix's own root)
    contributes nothing beyond whatever prefixes it's mounted under."""
    segments = [p.strip("/") for p in parts if p and p.strip("/")]
    joined = "/".join(segments)
    return "/" + joined if joined else "/"


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
            if method_text not in {"get", "post", "put", "delete", "patch"}:
                continue
            if _is_fstring(url_node):
                pattern = _reconstruct_fstring(url_node)
                path = _extract_path_from_pattern(pattern)
                if path is None:
                    continue
                results.append({
                    "url": path, "method": method_text.upper(),
                    "caller_function_name": _enclosing_py_function_name(url_node),
                })
                continue
            url_value = _node_string_value(url_node)
            if url_value is None:
                continue
            results.append({
                "url": url_value, "method": method_text.upper(),
                "caller_function_name": _enclosing_py_function_name(url_node),
            })
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
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
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
                if name_text in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    results.append({
                        "method": name_text, "path": api_path,
                        "spec_source": "nextjs_route", "function_name": name_text,
                    })

        return results
    except Exception:
        return []


def _is_fetch_call(match) -> bool:
    fn_node = match.get("fn")
    return fn_node is not None and fn_node.text.decode("utf-8") == "fetch"


def _is_axios_call(match, known_identifiers: frozenset[str] = frozenset({"axios"})) -> bool:
    lib_node = match.get("lib")
    method_node = match.get("method")
    if lib_node is None or method_node is None:
        return False
    if lib_node.text.decode("utf-8") not in known_identifiers:
        return False
    return method_node.text.decode("utf-8") in {"get", "post", "put", "delete", "patch"}


def file_exports_axios_instance(file_path: str) -> bool:
    """True if this file both creates a wrapped axios client (`<var> = axios.create(...)`)
    and exports that same variable as its default export (`export default <var>`).

    Lets a call site that imports a project's shared client (e.g. `import api from
    '@/lib/api'`, then `api.get(...)`) be recognized as an axios call even though it
    never references the literal identifier "axios" -- the standard way of centralizing
    baseURL/auth headers, and otherwise invisible to _is_axios_call's identifier check."""
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        root = tree.root_node

        instance_query = lang.query("""
(variable_declarator
  name: (identifier) @var
  value: (call_expression
    function: (member_expression
      object: (identifier) @lib
      property: (property_identifier) @method)))
""")
        instance_vars = set()
        for _, match in instance_query.matches(root):
            var_node = match.get("var")
            lib_node = match.get("lib")
            method_node = match.get("method")
            if var_node is None or lib_node is None or method_node is None:
                continue
            if lib_node.text.decode("utf-8") != "axios" or method_node.text.decode("utf-8") != "create":
                continue
            instance_vars.add(var_node.text.decode("utf-8"))
        if not instance_vars:
            return False

        export_query = lang.query("""
(export_statement value: (identifier) @name)
""")
        for _, match in export_query.matches(root):
            name_node = match.get("name")
            if name_node is not None and name_node.text.decode("utf-8") in instance_vars:
                return True
        return False
    except Exception:
        return False


def extract_default_imports(file_path: str) -> list[dict]:
    """Return every default import in this file as {"local_name", "source"}, e.g.
    `import api from '@/lib/api'` -> {"local_name": "api", "source": "@/lib/api"}.
    Used to trace whether a locally-named import resolves to a file that
    file_exports_axios_instance() recognizes as a wrapped axios client."""
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        results = []
        import_query = lang.query("""
(import_statement
  (import_clause (identifier) @local)
  source: (string (string_fragment) @source))
""")
        for _, match in import_query.matches(tree.root_node):
            local_node = match.get("local")
            source_node = match.get("source")
            if local_node is None or source_node is None:
                continue
            results.append({
                "local_name": local_node.text.decode("utf-8"),
                "source": source_node.text.decode("utf-8"),
            })
        return results
    except Exception:
        return []


def _js_string_literal_value(node) -> str | None:
    raw = node.text.decode("utf-8")
    if raw.startswith("`"):
        return None
    try:
        value = ast.literal_eval(raw)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _resolve_plain_string_url(url_node) -> str | None:
    return _js_string_literal_value(url_node)


def _axios_call_method(match, url_node) -> str:
    method_node = match.get("method")
    return method_node.text.decode("utf-8").upper() if method_node is not None else "GET"


def _fetch_call_method(match, url_node) -> str:
    # fetch(url) defaults to GET unless a second-argument options object
    # supplies an explicit method: "..." — mirrors the Fetch API's own default.
    args_node = url_node.parent
    if args_node is not None:
        for sibling in args_node.children:
            if sibling.type != "object":
                continue
            for prop in sibling.children:
                if prop.type != "pair":
                    continue
                key_node = prop.child_by_field_name("key")
                value_node = prop.child_by_field_name("value")
                if key_node is None or value_node is None or value_node.type != "string":
                    continue
                key_text = key_node.text.decode("utf-8").strip("'\"")
                if key_text != "method":
                    continue
                method_value = _js_string_literal_value(value_node)
                if method_value:
                    return method_value.upper()
    return "GET"


def _resolve_template_url(url_node, source: bytes) -> str | None:
    pattern = _reconstruct_template_string(url_node, source)
    return _extract_path_from_pattern(pattern)


def _collect_js_calls(query, tree_root, is_valid_call, resolve_url, resolve_method, file_path) -> list[dict]:
    out = []
    for _, match in query.matches(tree_root):
        url_node = match.get("url")
        if url_node is None or not is_valid_call(match):
            continue
        url = resolve_url(url_node)
        if url is not None:
            out.append({
                "url": url,
                "method": resolve_method(match, url_node),
                "file_path": file_path,
                "caller_function_name": _enclosing_js_function_name(url_node),
            })
    return out


def extract_js_http_calls(file_path: str, axios_identifiers: frozenset[str] = frozenset({"axios"})) -> list[dict]:
    try:
        lang, p = _get_js_parser(file_path)
        source = open(file_path, "rb").read()
        tree = p.parse(source)
        root = tree.root_node
        results = []

        def is_axios_call(match) -> bool:
            return _is_axios_call(match, axios_identifiers)

        # fetch("url")
        fetch_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (string) @url))
""")
        results += _collect_js_calls(fetch_query, root, _is_fetch_call, _resolve_plain_string_url, _fetch_call_method, file_path)

        # axios.get/post/put/delete("url") -- or a wrapped instance's local identifier,
        # e.g. api.get("url") where api = axios.create(...) (see axios_identifiers)
        axios_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @url))
""")
        results += _collect_js_calls(axios_query, root, is_axios_call, _resolve_plain_string_url, _axios_call_method, file_path)

        # fetch(`template literal`)
        fetch_template_query = lang.query("""
(call_expression
  function: (identifier) @fn
  arguments: (arguments
    (template_string) @url))
""")
        results += _collect_js_calls(
            fetch_template_query, root, _is_fetch_call,
            lambda url_node: _resolve_template_url(url_node, source), _fetch_call_method, file_path,
        )

        # axios.get/post/put/delete(`template literal`) -- or a wrapped instance's identifier
        axios_template_query = lang.query("""
(call_expression
  function: (member_expression
    object: (identifier) @lib
    property: (property_identifier) @method)
  arguments: (arguments
    (template_string) @url))
""")
        results += _collect_js_calls(
            axios_template_query, root, is_axios_call,
            lambda url_node: _resolve_template_url(url_node, source), _axios_call_method, file_path,
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
