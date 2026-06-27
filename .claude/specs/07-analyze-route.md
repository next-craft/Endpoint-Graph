# Spec 07 — POST /analyze Orchestrator

## Goal
Implement `backend/routers/analyze.py` with a `POST /analyze` route that orchestrates the full analysis pipeline: clone the repo, detect service folders, discover endpoints via OpenAPI YAML or route decorators, extract HTTP call sites, match URLs to known endpoint paths, and upsert all results into the database.

## Depends on
- Spec 01 (DB schema) — `services`, `endpoints`, and `consumer_edges` tables must exist
- Spec 03 (repo cloner) — `clone_repo` and `delete_repo` from `analysis/cloner.py`
- Spec 04 (OpenAPI parser) — `parse_service` from `analysis/spec_parser.py`
- Spec 05 (tree-sitter extractor) — `extract_route_decorators` and `extract_http_calls` from `analysis/code_parser.py`
- Spec 06 (URL matcher) — `match_url_to_endpoint` from `analysis/url_matcher.py`

## Context
This is the central integration point. All the analysis primitives (cloner, spec parser, code parser, URL matcher) exist in isolation. This route wires them together and writes results to PostgreSQL.

The user pastes a GitHub repo URL in the frontend. The frontend sends `POST /analyze` with `{repo_url: ...}` and an `X-GitHub-Token` header. This route:
1. Clones the repo into a temp dir
2. Scans the top-level subdirectories for service folders
3. For each service folder: discovers its exposed endpoints
4. Writes services + endpoints to DB
5. For each service folder: finds outbound HTTP calls, matches them to known endpoint paths across ALL services in DB, writes consumer_edges
6. Cleans up the temp dir
7. Returns counts of what was inserted

The `backend/main.py` must also be updated to register this router.

---

## Files to create
- `backend/routers/analyze.py` — the POST /analyze route implementation
- `backend/tests/test_routes.py` — integration tests for the analyze route (mocked DB and analysis functions)

## Files to edit
- `backend/main.py` — import and register the analyze router with `app.include_router(router)`

---

## Implementation details

### backend/routers/analyze.py

#### Imports

```python
import os
import glob
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from database import get_pool
from auth import get_github_token
from models import AnalyzeRequest, AnalyzeResponse
from analysis.cloner import clone_repo, delete_repo
from analysis.spec_parser import parse_service
from analysis.code_parser import extract_route_decorators, extract_http_calls
from analysis.url_matcher import match_url_to_endpoint

router = APIRouter()
```

---

#### Route definition

```python
@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, token: str = Depends(get_github_token)):
```

---

#### Step-by-step implementation inside `analyze()`

**Step 1 — Clone the repo**

Initialize `tmp_dir = None` before the try block so the `finally` clause can guard against `NameError` if `clone_repo` raises before assignment:

```python
tmp_dir = None
try:
    tmp_dir = clone_repo(request.repo_url, token)
    # ... all analysis steps (Steps 2–6) ...
except ValueError as e:
    raise HTTPException(status_code=422, detail=str(e))
except RuntimeError as e:
    raise HTTPException(status_code=400, detail=str(e))
finally:
    if tmp_dir:
        delete_repo(tmp_dir)
```

- `clone_repo` raises `ValueError` for an invalid URL → caught, re-raised as HTTP 422.
- `clone_repo` raises `RuntimeError` for a failed clone (bad token, repo not found) → caught, re-raised as HTTP 400.
- Any other unexpected exception propagates normally; `delete_repo` still runs via `finally`.
- All Steps 2–6 live inside the `try` block.

---

**Step 2 — Detect service folders**

A service folder is any **immediate subdirectory** of `tmp_dir` that contains:
- an `openapi.yaml` or `openapi.json` file, OR
- at least one `.py` file

Check with:
```python
def _is_service_folder(folder_path: str) -> bool:
    has_openapi = (
        os.path.exists(os.path.join(folder_path, "openapi.yaml")) or
        os.path.exists(os.path.join(folder_path, "openapi.json"))
    )
    has_python = bool(glob.glob(os.path.join(folder_path, "*.py")))
    return has_openapi or has_python
```

Scan:
```python
service_folders = [
    os.path.join(tmp_dir, entry)
    for entry in os.listdir(tmp_dir)
    if os.path.isdir(os.path.join(tmp_dir, entry))
    and _is_service_folder(os.path.join(tmp_dir, entry))
]
```

The service `name` is `os.path.basename(folder_path)`.

---

**Step 3 — Discover endpoints for each service folder**

For each service folder call `parse_service(folder_path)` from `analysis/spec_parser.py`. This function:
- Looks for `openapi.yaml` or `openapi.json` inside the folder
- Returns `{"service_name": str, "endpoints": list[dict]}` if an OpenAPI file is found
- Returns `None` if no OpenAPI file exists

```python
result = parse_service(folder_path)
if result is not None:
    # OpenAPI path — endpoints already have spec_source = "openapi"
    discovered = result["endpoints"]
else:
    # Decorator fallback — scan .py files
    discovered = []
    for py_file in glob.glob(os.path.join(folder_path, "*.py")):
        for ep in extract_route_decorators(py_file):
            discovered.append({
                "method": ep["method"],
                "path": ep["path"],
                "spec_source": "decorator",
            })
```

**Service name:** Always use `os.path.basename(folder_path)` as the service name, regardless of what `parse_service` returns in `result["service_name"]`. The OpenAPI `info.title` field is ignored for naming in v1 — folder name is authoritative.

Collect results as a list of `{"method": str, "path": str, "spec_source": str}` in `discovered`.

---

**Step 4 — Upsert services and endpoints into DB**

Initialize counters and the service records list at the top of the function body (before the try block):

```python
services_count = 0
endpoints_count = 0
edges_count = 0
service_records = []  # list of (service_name, service_id, folder_path) tuples
```

Get the asyncpg pool and open one connection for all service/endpoint inserts:

```python
pool = await get_pool()
async with pool.acquire() as conn:
    for folder_path in service_folders:
        service_name = os.path.basename(folder_path)

        # Discover endpoints (Step 3 logic runs here, inline)
        # ... discovered = [{"method", "path", "spec_source"}, ...]

        # Get or create the service record
        row = await conn.fetchrow(
            "SELECT id FROM services WHERE name = $1 AND repo_url = $2",
            service_name, request.repo_url
        )
        if row:
            service_id = row["id"]
        else:
            service_id = await conn.fetchval(
                "INSERT INTO services (name, language, repo_url) VALUES ($1, $2, $3) RETURNING id",
                service_name, "python", request.repo_url
            )
            services_count += 1

        service_records.append((service_name, service_id, folder_path))

        # Get or create each endpoint record
        for endpoint in discovered:
            ep_row = await conn.fetchrow(
                "SELECT id FROM endpoints WHERE service_id = $1 AND method = $2 AND path = $3",
                service_id, endpoint["method"], endpoint["path"]
            )
            if not ep_row:
                await conn.execute(
                    "INSERT INTO endpoints (service_id, method, path, spec_source) VALUES ($1, $2, $3, $4)",
                    service_id, endpoint["method"], endpoint["path"], endpoint["spec_source"]
                )
                endpoints_count += 1
```

`services_count` increments only when a new service row is inserted. `endpoints_count` increments only when a new endpoint row is inserted. Re-running the analysis on the same repo increments neither.

---

**Step 5 — Load all known endpoint paths from DB**

After all services and endpoints are written, load the full set of known endpoints so that HTTP call sites can be matched against them. Include `service_id` so the self-edge check in Step 6 can avoid a per-edge DB round trip:

```python
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT id, method, path, service_id FROM endpoints")

known_endpoints = [
    {"id": r["id"], "method": r["method"], "path": r["path"], "service_id": r["service_id"]}
    for r in rows
]
known_paths = [e["path"] for e in known_endpoints]
```

This queries ALL endpoints across ALL services in the DB — not just the ones added in this run — so that cross-repo consumer relationships can be resolved on future re-analyses.

---

**Step 6 — Extract HTTP call sites and build consumer_edges**

Open a new connection for the edge-writing loop (Step 5's connection is already closed):

```python
async with pool.acquire() as conn:
    for service_name, service_id, folder_path in service_records:
        py_files = glob.glob(os.path.join(folder_path, "*.py"))
        for py_file in py_files:
            calls = extract_http_calls(py_file)
            for call in calls:
                url_path = _extract_path(call["url"])
                if not url_path:
                    continue
                matched_path = match_url_to_endpoint(url_path, known_paths)
                if matched_path is None:
                    continue
                # Find the endpoint record for this path.
                # If multiple endpoints share the same path (different methods),
                # the first match in known_endpoints is used. This is acceptable
                # in v1 — goal is service-level dependency tracking, not method-level.
                matched_endpoint = next(
                    (e for e in known_endpoints if e["path"] == matched_path), None
                )
                if matched_endpoint is None:
                    continue
                endpoint_id = matched_endpoint["id"]
                # Skip self-edges: a service calling its own endpoint is not a consumer relationship.
                if matched_endpoint["service_id"] == service_id:
                    continue
                # Upsert consumer_edge
                await conn.execute("""
                    INSERT INTO consumer_edges (caller_service_id, endpoint_id, last_seen_at, call_count, source)
                    VALUES ($1, $2, NOW(), 1, 'static')
                    ON CONFLICT (caller_service_id, endpoint_id)
                    DO UPDATE SET last_seen_at = NOW(), source = 'static'
                """, service_id, endpoint_id)
                edges_count += 1
```

`_extract_path` is a module-level helper (defined outside the route function):

```python
def _extract_path(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.path if parsed.path else None
```

There is no `_get_service_id_for_endpoint` helper — the self-edge check uses `matched_endpoint["service_id"]` which was loaded in Step 5's SELECT.

`edges_count` is incremented for every upsert executed (including updates on re-runs, not only new inserts).

---

**Step 7 — Return response**

```python
return AnalyzeResponse(
    status="ok",
    services=services_count,
    endpoints=endpoints_count,
    edges=edges_count
)
```

`services_count` = number of new service rows inserted.
`endpoints_count` = number of new endpoint rows inserted.
`edges_count` = number of consumer_edge upserts executed (includes updates, not just new inserts).

---

### backend/main.py

Add to the existing file (do not overwrite — only add the router registration):

```python
from routers.analyze import router as analyze_router
app.include_router(analyze_router)
```

Place this alongside any other `include_router` calls.

---

### models.py

`AnalyzeRequest` and `AnalyzeResponse` should already exist from the project skeleton (per CLAUDE.md). If they do not, add:

```python
class AnalyzeRequest(BaseModel):
    repo_url: str

class AnalyzeResponse(BaseModel):
    status: str
    services: int
    endpoints: int
    edges: int
```

Do not duplicate them if they already exist.

---

## Test cases

All tests go in `backend/tests/test_routes.py`.

Use `pytest` with `unittest.mock.patch` to mock the analysis functions and DB pool. Do not make real network calls or real DB connections in these tests.

- **`test_analyze_returns_ok_status`** — create a real temp dir via `tmp_path` fixture with one subdirectory containing a single `.py` file (so `_is_service_folder` returns True organically). Mock `clone_repo` to return that temp dir path. Mock `parse_service` to return `None` (so the decorator path is used). Mock `extract_route_decorators` to return `[{"method": "GET", "path": "/items"}]`. Mock the DB pool so `fetchrow` returns `None` (new service) and `fetchval` returns `1` (new service_id). Mock `extract_http_calls` to return `[]`. Assert response body has `status == "ok"` and `services == 1`.

- **`test_analyze_invalid_github_url`** — mock `clone_repo` to raise `ValueError("Invalid GitHub URL: ...")`. POST `/analyze` with a bad URL. Assert HTTP 422 is returned.

- **`test_analyze_clone_failure`** — mock `clone_repo` to raise `RuntimeError("Clone failed: ...")`. POST `/analyze`. Assert HTTP 400 is returned.

- **`test_analyze_calls_delete_repo_on_success`** — mock `clone_repo` and full pipeline. Assert `delete_repo` was called exactly once with the temp dir path (use `mock.assert_called_once_with`).

- **`test_analyze_calls_delete_repo_on_error`** — mock `clone_repo` to succeed, mock `parse_service` to raise an unexpected exception. Assert `delete_repo` was still called (cleanup always runs).

- **`test_analyze_uses_openapi_when_present`** — create a real temp folder with a minimal `openapi.yaml` and a `.py` file. Mock `parse_service` to return `{"service_name": "svc", "endpoints": []}` and mock `extract_route_decorators`. Assert `parse_service` was called and `extract_route_decorators` was NOT called.

- **`test_analyze_falls_back_to_decorators`** — temp folder with only a `.py` file (no openapi.yaml). Mock `parse_service` to return `None`. Assert `extract_route_decorators` was called.

- **`test_analyze_skips_non_service_folders`** — temp dir with one subfolder that contains no `.py` files and no `openapi.yaml`. Assert `services_count = 0`.

- **`test_analyze_consumer_edge_upserted`** — mock `extract_http_calls` to return `[{"url": "http://user-service/users/123"}]`, mock DB to have `/users/{id}` as a known path. Assert the upsert SQL was executed with the correct endpoint id.

- **`test_analyze_skips_fqdn_paths_that_dont_match`** — mock `extract_http_calls` to return `[{"url": "http://unknown-service/unknown/path"}]`. Assert no `consumer_edge` insert was attempted.

- **`test_analyze_no_self_edges`** — service A exposes `GET /items/{id}` and also has a call to `http://service-a/items/1`. Assert no consumer_edge is inserted (a service calling its own endpoint is not a consumer relationship).

- **`test_extract_path_helper`** — unit test `_extract_path` directly: `_extract_path("http://user-service/users/123")` → `"/users/123"`, `_extract_path("")` → `None`, `_extract_path("http://svc")` → `""` or `"/"` (empty path is falsy — the route skips it).

---

## Done when

- [ ] `backend/routers/analyze.py` exists with `POST /analyze` route
- [ ] Route has signature `async def analyze(request: AnalyzeRequest, token: str = Depends(get_github_token))`
- [ ] `clone_repo` is called with `request.repo_url` and `token`
- [ ] `tmp_dir` is initialized to `None` before the try block; `finally` guards with `if tmp_dir: delete_repo(tmp_dir)`
- [ ] Clone `ValueError` → HTTP 422; clone `RuntimeError` → HTTP 400
- [ ] Service detection checks top-level subdirectories only (not recursive)
- [ ] `parse_service(folder_path)` is used for OpenAPI discovery; `extract_route_decorators` is the fallback when `parse_service` returns `None`
- [ ] Service name is always `os.path.basename(folder_path)` — OpenAPI `info.title` is ignored
- [ ] `service_records` list is initialized before the service loop and populated with `(service_name, service_id, folder_path)` tuples
- [ ] Service upsert uses SELECT + conditional INSERT (no UNIQUE constraint on services table)
- [ ] Endpoint upsert uses SELECT + conditional INSERT (no UNIQUE constraint on endpoints table)
- [ ] Step 5 SELECT includes `service_id`: `SELECT id, method, path, service_id FROM endpoints`
- [ ] Step 6 opens its own `async with pool.acquire() as conn:` block
- [ ] Self-edge check uses `matched_endpoint["service_id"] == service_id` (no extra DB query)
- [ ] Consumer edges use the SQL `ON CONFLICT (caller_service_id, endpoint_id) DO UPDATE` upsert
- [ ] `source` field on consumer_edges is always `'static'` in v1
- [ ] `_extract_path` is a module-level function that strips scheme+host from a full URL
- [ ] No `_get_service_id_for_endpoint` helper exists — self-edge check is inline
- [ ] All known endpoint paths from ALL services in DB are loaded before matching
- [ ] `backend/main.py` registers the analyze router
- [ ] `AnalyzeResponse` fields `services`, `endpoints`, `edges` are all integers ≥ 0
- [ ] All 12 test cases listed above pass
- [ ] No hardcoded credentials or absolute paths
- [ ] No TypeScript — this is a backend-only spec, all files are `.py`
- [ ] No ORM — raw asyncpg queries only
