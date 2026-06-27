# Spec 08 — Remaining GET Routes

## Goal
Implement GET /services, GET /endpoints, GET /endpoints/{id}/impact-analysis, and GET /graph in their own router files, then register all routers in main.py.

## Depends on
Specs 01 (DB schema), 07 (POST /analyze — establishes the pool pattern and auth dependency). All Pydantic models (ServiceOut, EndpointOut, ConsumerOut, GraphNode, GraphEdge, GraphOut) already exist in models.py.

## Context
POST /analyze (spec 07) is the only registered route right now. main.py has commented-out stubs for the three remaining routers. This spec fills them in. The four GET routes are the read side of the API — the frontend calls these to render the graph, the side panel, and the services/endpoints lists. All routes require the X-GitHub-Token header (enforced by the shared `get_github_token` dependency in auth.py).

## Files to create
- `backend/routers/services.py` — GET /services: returns all rows from the services table
- `backend/routers/endpoints.py` — GET /endpoints (optional ?service_id filter) and GET /endpoints/{id}/impact-analysis
- `backend/routers/graph.py` — GET /graph: fetches all services as nodes and all consumer edges as graph edges

## Files to edit
- `backend/main.py` — import and register the three new routers; remove the commented-out stubs
- `backend/tests/test_routes.py` — add test cases for all four new routes

## Implementation details

### backend/routers/services.py

One route:

`GET /services`
- Dependency: `token: str = Depends(get_github_token)` (enforces auth; token value not used in query)
- Response model: `list[ServiceOut]`
- SQL:
  ```sql
  SELECT id, name, language, repo_url FROM services ORDER BY id
  ```
- Returns the rows directly as a list; empty list if no services exist

```python
from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token
from models import ServiceOut

router = APIRouter()

@router.get("/services", response_model=list[ServiceOut])
async def get_services(token: str = Depends(get_github_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, language, repo_url FROM services ORDER BY id"
        )
    return [
        ServiceOut(id=r["id"], name=r["name"], language=r["language"], repo_url=r["repo_url"])
        for r in rows
    ]
```

---

### backend/routers/endpoints.py

Two routes:

**`GET /endpoints`**
- Query param: `service_id: int | None = None`
- Dependency: `token: str = Depends(get_github_token)`
- Response model: `list[EndpointOut]`
- SQL (no filter):
  ```sql
  SELECT id, service_id, method, path, spec_source FROM endpoints ORDER BY id
  ```
- SQL (with filter):
  ```sql
  SELECT id, service_id, method, path, spec_source FROM endpoints WHERE service_id = $1 ORDER BY id
  ```
- Returns empty list if no rows match

**`GET /endpoints/{id}/impact-analysis`**
- Path param: `endpoint_id: int` (the `{id}` in the URL, use `id` as the FastAPI path param name)
- Dependency: `token: str = Depends(get_github_token)`
- Response model: `list[ConsumerOut]`
- SQL (verbatim from CLAUDE.md):
  ```sql
  SELECT s.name AS service_name, ce.call_count, ce.last_seen_at, ce.source
  FROM consumer_edges ce
  JOIN services s ON s.id = ce.caller_service_id
  WHERE ce.endpoint_id = $1
  ORDER BY ce.call_count DESC
  ```
- Returns empty list if no consumers

```python
from fastapi import APIRouter, Depends
from typing import Optional
from database import get_pool
from auth import get_github_token
from models import EndpointOut, ConsumerOut

router = APIRouter()

@router.get("/endpoints", response_model=list[EndpointOut])
async def get_endpoints(
    service_id: Optional[int] = None,
    token: str = Depends(get_github_token),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if service_id is not None:
            rows = await conn.fetch(
                "SELECT id, service_id, method, path, spec_source"
                " FROM endpoints WHERE service_id = $1 ORDER BY id",
                service_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, service_id, method, path, spec_source"
                " FROM endpoints ORDER BY id"
            )
    return [
        EndpointOut(
            id=r["id"],
            service_id=r["service_id"],
            method=r["method"],
            path=r["path"],
            spec_source=r["spec_source"],
        )
        for r in rows
    ]


@router.get("/endpoints/{id}/impact-analysis", response_model=list[ConsumerOut])
async def get_impact_analysis(id: int, token: str = Depends(get_github_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT s.name AS service_name, ce.call_count, ce.last_seen_at, ce.source"
            " FROM consumer_edges ce"
            " JOIN services s ON s.id = ce.caller_service_id"
            " WHERE ce.endpoint_id = $1"
            " ORDER BY ce.call_count DESC",
            id,
        )
    return [
        ConsumerOut(
            service_name=r["service_name"],
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
            source=r["source"],
        )
        for r in rows
    ]
```

---

### backend/routers/graph.py

One route:

**`GET /graph`**
- Dependency: `token: str = Depends(get_github_token)`
- Response model: `GraphOut`
- Two queries — run them inside the same acquired connection:

  Query 1 — all services (become nodes):
  ```sql
  SELECT id, name FROM services ORDER BY id
  ```

  Query 2 — all edges (join to get the provider service id):
  ```sql
  SELECT
    ce.caller_service_id,
    e.service_id AS provider_service_id,
    e.path AS endpoint_path,
    e.method AS endpoint_method,
    ce.call_count,
    ce.last_seen_at
  FROM consumer_edges ce
  JOIN endpoints e ON e.id = ce.endpoint_id
  ```

- Build nodes: for each row from query 1, `GraphNode(id=str(row["id"]), name=row["name"])`
- Build edges: for each row from query 2:
  ```python
  GraphEdge(
      source=str(row["caller_service_id"]),
      target=str(row["provider_service_id"]),
      endpoint_path=row["endpoint_path"],
      endpoint_method=row["endpoint_method"],
      call_count=row["call_count"],
      last_seen_at=row["last_seen_at"],
  )
  ```
- Returns `GraphOut(nodes=nodes, edges=edges)`; both lists are empty if the DB has no data

```python
from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()

@router.get("/graph", response_model=GraphOut)
async def get_graph(token: str = Depends(get_github_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        service_rows = await conn.fetch("SELECT id, name FROM services ORDER BY id")
        edge_rows = await conn.fetch(
            "SELECT ce.caller_service_id, e.service_id AS provider_service_id,"
            " e.path AS endpoint_path, e.method AS endpoint_method,"
            " ce.call_count, ce.last_seen_at"
            " FROM consumer_edges ce"
            " JOIN endpoints e ON e.id = ce.endpoint_id"
        )

    nodes = [GraphNode(id=str(r["id"]), name=r["name"]) for r in service_rows]
    edges = [
        GraphEdge(
            source=str(r["caller_service_id"]),
            target=str(r["provider_service_id"]),
            endpoint_path=r["endpoint_path"],
            endpoint_method=r["endpoint_method"],
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
        )
        for r in edge_rows
    ]
    return GraphOut(nodes=nodes, edges=edges)
```

---

### backend/main.py changes

Replace the commented-out router block with real imports and registration:

```python
from routers.analyze import router as analyze_router
from routers.services import router as services_router
from routers.endpoints import router as endpoints_router
from routers.graph import router as graph_router

# ...

app.include_router(analyze_router)
app.include_router(services_router)
app.include_router(endpoints_router)
app.include_router(graph_router)
```

Remove the comment block:
```python
# Remaining routers registered here as specs are implemented:
# from routers import services, endpoints, graph
# app.include_router(services.router)
# app.include_router(endpoints.router)
# app.include_router(graph.router)
```

---

### backend/tests/test_routes.py additions

Add these test cases after the existing analyze tests. Use the same `_Row`, `_make_pool`, `HEADERS`, and `AsyncClient` / `ASGITransport` pattern already in the file.

Add a `datetime` import at the top of the file: `from datetime import datetime, timezone`

**GET /services tests**

`test_get_services_returns_list`
- Pool returns two rows: `[_Row({"id": 1, "name": "order-service", "language": "python", "repo_url": "github.com/x/y"}), _Row({"id": 2, "name": "user-service", "language": None, "repo_url": None})]`
- GET /services with HEADERS
- Assert status 200, response is list of length 2
- Assert first item has `"name": "order-service"`

`test_get_services_empty`
- Pool returns `[]`
- GET /services with HEADERS
- Assert status 200, response is `[]`

`test_get_services_requires_token`
- GET /services with no headers (no X-GitHub-Token)
- Assert status 422 (FastAPI validation error — missing required header)

**GET /endpoints tests**

`test_get_endpoints_returns_all`
- Pool returns two endpoint rows:
  ```python
  [
      _Row({"id": 1, "service_id": 1, "method": "GET", "path": "/users/{id}", "spec_source": "openapi"}),
      _Row({"id": 2, "service_id": 2, "method": "POST", "path": "/orders/create", "spec_source": "decorator"}),
  ]
  ```
- GET /endpoints with HEADERS
- Assert status 200, list of length 2
- Assert first item has `"path": "/users/{id}"` and `"service_id": 1`

`test_get_endpoints_filters_by_service_id`
- Pool returns one row:
  ```python
  [_Row({"id": 1, "service_id": 1, "method": "GET", "path": "/users/{id}", "spec_source": "openapi"})]
  ```
- GET /endpoints?service_id=1 with HEADERS
- Assert status 200, list of length 1
- Assert the row has `"service_id": 1` and `"path": "/users/{id}"`

`test_get_endpoints_requires_token`
- GET /endpoints with no token
- Assert status 422

**GET /endpoints/{id}/impact-analysis tests**

`test_get_impact_analysis_returns_consumers`
- Pool returns two consumer rows:
  ```python
  _Row({"service_name": "order-service", "call_count": 5, "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "source": "static"})
  _Row({"service_name": "payment-service", "call_count": 2, "last_seen_at": datetime(2024, 1, 2, tzinfo=timezone.utc), "source": "static"})
  ```
- GET /endpoints/1/impact-analysis with HEADERS
- Assert status 200, list of length 2
- Assert first item `service_name == "order-service"` and `call_count == 5`

`test_get_impact_analysis_empty`
- Pool returns `[]`
- GET /endpoints/99/impact-analysis with HEADERS
- Assert status 200, response is `[]`

`test_get_impact_analysis_requires_token`
- GET /endpoints/1/impact-analysis with no token
- Assert status 422

**GET /graph tests**

`test_get_graph_returns_nodes_and_edges`
- First conn.fetch call (services): two rows:
  ```python
  [_Row({"id": 1, "name": "order-service"}), _Row({"id": 2, "name": "user-service"})]
  ```
- Second conn.fetch call (edges): one row:
  ```python
  [_Row({"caller_service_id": 1, "provider_service_id": 2, "endpoint_path": "/users/{id}", "endpoint_method": "GET", "call_count": 10, "last_seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})]
  ```
- Use `conn.fetch = AsyncMock(side_effect=[service_rows, edge_rows])`
- GET /graph with HEADERS
- Assert status 200
- Assert `data["nodes"]` has length 2
- Assert `data["nodes"][0] == {"id": "1", "name": "order-service"}`
- Assert `data["edges"]` has length 1
- Assert `data["edges"][0]["source"] == "1"` and `data["edges"][0]["target"] == "2"`

`test_get_graph_empty_db`
- Use `conn.fetch = AsyncMock(side_effect=[[], []])` so the first call (services) and second call (edges) both return empty lists
- GET /graph with HEADERS
- Assert status 200, `nodes == []`, `edges == []`

`test_get_graph_requires_token`
- GET /graph with no token
- Assert status 422

Each test that needs a pool must patch `routers.<module>.get_pool` (e.g., `routers.services.get_pool`, `routers.endpoints.get_pool`, `routers.graph.get_pool`) using `patch(..., new_callable=AsyncMock)` returning `_make_pool(conn)`.

## Test cases

- `test_get_services_returns_list` — /services returns list with correct fields
- `test_get_services_empty` — /services returns empty list when DB has no rows
- `test_get_services_requires_token` — /services without X-GitHub-Token returns 422
- `test_get_endpoints_returns_all` — /endpoints returns all endpoints across services
- `test_get_endpoints_filters_by_service_id` — /endpoints?service_id=1 returns only that service's endpoints
- `test_get_endpoints_requires_token` — /endpoints without token returns 422
- `test_get_impact_analysis_returns_consumers` — /endpoints/1/impact-analysis returns list ordered by call_count desc
- `test_get_impact_analysis_empty` — /endpoints/99/impact-analysis returns empty list
- `test_get_impact_analysis_requires_token` — /endpoints/1/impact-analysis without token returns 422
- `test_get_graph_returns_nodes_and_edges` — /graph returns nodes list and edges list with correct shapes
- `test_get_graph_empty_db` — /graph returns empty nodes and edges when DB is empty
- `test_get_graph_requires_token` — /graph without token returns 422

## Done when

- [ ] `backend/routers/services.py` exists and implements `GET /services`
- [ ] `backend/routers/endpoints.py` exists and implements `GET /endpoints` and `GET /endpoints/{id}/impact-analysis`
- [ ] `backend/routers/graph.py` exists and implements `GET /graph`
- [ ] `backend/main.py` imports and registers all three new routers; the commented-out stubs are removed
- [ ] All 12 new test cases in `test_routes.py` pass
- [ ] All previously passing tests still pass (no regressions)
- [ ] No TypeScript — not applicable (backend only)
- [ ] No hardcoded credentials
- [ ] Raw asyncpg queries only — no ORM
- [ ] All routes use `Depends(get_github_token)` from auth.py
