# Spec 04 — OpenAPI Spec Parser

## Goal
Parse an `openapi.yaml` (or `openapi.json`) file from a cloned repo directory and return a structured list of endpoints ready for insertion into the `endpoints` table.

## Depends on
- Spec 01 — DB schema must exist (`services` and `endpoints` tables)
- Spec 03 — Repo cloner must work so there is a local directory to parse

## Context
This is the first analysis step after cloning a repo. When a service ships an `openapi.yaml`, it is the most reliable source of endpoint data — more trustworthy than decorator scanning because it is explicitly authored by the service owner. The `spec_source` column on the `endpoints` table records how an endpoint was discovered; this parser sets it to `"openapi"`.

The parser lives at `backend/analysis/spec_parser.py`. It is called by `POST /analyze` (Spec 07) after the repo is cloned. If no OpenAPI file is found, the caller falls back to the tree-sitter extractor (Spec 05).

From CLAUDE.md:
> When analyzing a service folder, check in this order:
> 1. `openapi.yaml` or `openapi.json` exists → parse with PyYAML (most reliable)
> 2. No spec file → scan `.py` files with tree-sitter for route decorators

## Files to create
- `backend/analysis/spec_parser.py` — reads an OpenAPI file and returns a list of endpoint dicts
- `backend/tests/test_spec_parser.py` — unit tests for the parser

## Files to edit
- `backend/requirements.txt` — `pyyaml` must be listed with a pinned version

## Implementation details

### backend/analysis/spec_parser.py

#### `find_openapi_file(service_dir: str) -> str | None`

Looks for an OpenAPI file in the given directory (not recursive — top-level only).

- Checks for `openapi.yaml` first, then `openapi.json`
- Uses `os.path.join(service_dir, filename)` and `os.path.isfile()`
- Returns the full path if found, `None` if neither exists

#### `parse_openapi_file(file_path: str) -> dict`

Loads the OpenAPI file and returns the raw parsed dict.

- Opens the file with `open(file_path, "r", encoding="utf-8")`
- Calls `yaml.safe_load(f)` — works for both `.yaml` and `.json` (PyYAML can parse JSON)
- Raises `ValueError` with a message if the result is not a dict (e.g. file is empty or malformed)
- Returns the raw dict (callers extract what they need)

#### `extract_service_name(spec: dict) -> str`

Extracts the service name from the parsed spec.

- Gets `info = spec.get("info")` — if `info` is missing or not a dict (e.g. `None`), returns `"unknown"`
- Otherwise returns `info.get("title", "unknown")`
- Never raises — always returns a string

#### `extract_endpoints(spec: dict) -> list[dict]`

Extracts all endpoints from the `paths` section and returns a list of dicts.

Return type — each dict in the list has exactly these keys:
```python
{
    "method": str,       # uppercase: "GET", "POST", "PUT", "DELETE", "PATCH"
    "path": str,         # exactly as written in the YAML, e.g. "/users/{id}"
    "spec_source": str,  # always "openapi"
}
```

Logic:
- If `"paths"` key is missing from `spec`, return `[]`
- Iterate over `spec["paths"].items()` → `(path_str, path_item)`
- For each `path_item`, iterate over its keys
- Only include keys that are in the allowed method set: `{"get", "post", "put", "delete", "patch"}` — all other keys (including `"options"`, `"head"`, `"summary"`, `"parameters"`, etc.) are skipped
- For each matching method key, append:
  ```python
  {"method": method.upper(), "path": path_str, "spec_source": "openapi"}
  ```
- If a path item's value is `None` (e.g. a YAML path entry with no content), skip it entirely and continue to the next path
- Skip any path item key that is not in the allowed method set
- Return the full list (may be empty if paths has entries but no recognized methods)

#### `parse_service(service_dir: str) -> dict | None`

Top-level function called by the analyze router. Combines all of the above.

Signature:
```python
def parse_service(service_dir: str) -> dict | None:
```

Returns:
```python
{
    "service_name": str,         # from extract_service_name
    "endpoints": list[dict],     # from extract_endpoints, each with method/path/spec_source
}
```

Returns `None` if no OpenAPI file is found in `service_dir` (signals to caller to fall back to tree-sitter).

Logic:
1. Call `find_openapi_file(service_dir)` — if `None`, return `None`
2. Call `parse_openapi_file(file_path)` — let any `ValueError` propagate (caller handles it)
3. Call `extract_service_name(spec)`
4. Call `extract_endpoints(spec)`
5. Return the assembled dict

### backend/requirements.txt

Ensure `pyyaml` is present with a pinned version, e.g.:
```
pyyaml==6.0.1
```

## Test cases

Tests go in `backend/tests/test_spec_parser.py`. Use `pytest`. No async needed — all functions are synchronous.

Use `tmp_path` (pytest fixture) or `tempfile.mkdtemp()` to create temporary YAML files — do not rely on fixture files on disk.

### Test list

- `test_find_openapi_file_yaml` — creates a temp dir with `openapi.yaml`, asserts `find_openapi_file` returns the full path to it
- `test_find_openapi_file_json` — creates a temp dir with `openapi.json` (no `.yaml`), asserts path returned
- `test_find_openapi_file_yaml_takes_priority` — creates temp dir with both `openapi.yaml` and `openapi.json`, asserts `.yaml` path is returned
- `test_find_openapi_file_missing` — creates an empty temp dir, asserts `find_openapi_file` returns `None`
- `test_parse_openapi_file_valid` — writes a minimal valid YAML to disk, asserts `parse_openapi_file` returns a dict
- `test_parse_openapi_file_empty` — writes an empty file to disk, asserts `ValueError` is raised
- `test_parse_openapi_file_non_dict` — writes YAML that is a list (`- item1`), asserts `ValueError` is raised
- `test_extract_service_name_present` — passes `{"info": {"title": "Order Service"}}`, asserts `"Order Service"` returned
- `test_extract_service_name_missing_info` — passes `{}`, asserts `"unknown"` returned
- `test_extract_service_name_missing_title` — passes `{"info": {}}`, asserts `"unknown"` returned
- `test_extract_service_name_info_is_none` — passes `{"info": None}`, asserts `"unknown"` returned without raising
- `test_extract_endpoints_basic` — passes a spec with one path `/users/{id}` having `get` and `post`, asserts list of 2 dicts with correct method/path/spec_source
- `test_extract_endpoints_filters_non_methods` — path item has `"summary"`, `"parameters"`, `"get"` keys; asserts only the `get` entry appears
- `test_extract_endpoints_excludes_options_and_head` — path item has `"options"`, `"head"`, and `"get"` keys; asserts only the `get` entry appears in output
- `test_extract_endpoints_null_path_item` — spec has `{"paths": {"/users/{id}": None}}`; asserts function returns `[]` without raising
- `test_extract_endpoints_empty_paths` — passes `{"paths": {}}`, asserts `[]` returned
- `test_extract_endpoints_missing_paths` — passes `{}`, asserts `[]` returned
- `test_extract_endpoints_methods_uppercase` — asserts method values are `"GET"` not `"get"`
- `test_extract_endpoints_spec_source` — asserts every returned dict has `"spec_source": "openapi"`
- `test_parse_service_returns_none_when_no_file` — empty temp dir, asserts `parse_service` returns `None`
- `test_parse_service_malformed_file` — writes an empty `openapi.yaml` to a temp dir, asserts `parse_service` raises `ValueError`
- `test_parse_service_full_flow` — writes a valid `openapi.yaml` with `info.title` and two endpoints, asserts returned dict has correct `service_name` and two-item `endpoints` list

### Minimal YAML fixture for tests

```python
SAMPLE_OPENAPI = """
openapi: "3.0.0"
info:
  title: "User Service"
  version: "1.0.0"
paths:
  /users/{id}:
    get:
      summary: Get user by ID
    post:
      summary: Update user
  /users/profile:
    get:
      summary: Get current user profile
"""
```

## Done when

- [ ] `backend/analysis/spec_parser.py` exists with all five functions: `find_openapi_file`, `parse_openapi_file`, `extract_service_name`, `extract_endpoints`, `parse_service`
- [ ] All function signatures match exactly what is specified above
- [ ] `parse_service` returns `None` (not raises) when no OpenAPI file is found
- [ ] `parse_openapi_file` raises `ValueError` on empty/non-dict files
- [ ] `extract_service_name` never raises — always returns a string
- [ ] `extract_endpoints` only includes `get`, `post`, `put`, `delete`, `patch` methods; skips all others
- [ ] All method strings in output are uppercase
- [ ] All `spec_source` values are `"openapi"`
- [ ] `backend/tests/test_spec_parser.py` exists and all 22 test cases listed above pass
- [ ] `pyyaml` is in `requirements.txt` with a pinned version
- [ ] No TypeScript, no Docker, no ORMs, no hardcoded credentials
