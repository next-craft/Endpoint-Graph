from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()

GRAPH_QUERY = """
SELECT
  e.id               AS endpoint_id,
  e.service_id       AS endpoint_service_id,
  es.name            AS endpoint_service_name,
  e.file_path        AS endpoint_file_path,
  e.function_name    AS endpoint_function_name,
  e.method, e.path,
  ce.caller_service_id,
  cs.name            AS caller_service_name,
  ce.caller_file_path,
  ce.caller_function_name,
  ce.call_count, ce.last_seen_at
FROM consumer_edges ce
JOIN services cs ON cs.id = ce.caller_service_id
JOIN endpoints e  ON e.id  = ce.endpoint_id
JOIN services es  ON es.id = e.service_id
WHERE cs.repo_id = $1
"""

# consumer_edges only ever yields rows for cross-service calls (analyze.py
# excludes self-calls), so a tracked single-service monolith always has zero
# edges. These counts let the frontend tell "not tracked" apart from "tracked,
# just no cross-service callers" even though GRAPH_QUERY returns no rows for
# either case.
COUNTS_QUERY = """
SELECT
  (SELECT COUNT(*) FROM services WHERE repo_id = $1) AS service_count,
  (SELECT COUNT(*) FROM endpoints e JOIN services s ON s.id = e.service_id WHERE s.repo_id = $1) AS endpoint_count
"""


@router.get("/graph", response_model=GraphOut)
async def get_graph(
    repo_id: str,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            rows = await conn.fetch(GRAPH_QUERY, repo_id)
            counts_row = await conn.fetchrow(COUNTS_QUERY, repo_id)

    endpoint_nodes: dict[str, GraphNode] = {}
    caller_nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for r in rows:
        ep_id = f"ep:{r['endpoint_id']}"
        if ep_id not in endpoint_nodes:
            function_name = r["endpoint_function_name"]
            label = f"{function_name}\n{r['method']} {r['path']}" if function_name else f"{r['method']} {r['path']}"
            endpoint_nodes[ep_id] = GraphNode(
                id=ep_id,
                node_type="endpoint",
                label=label,
                function_name=function_name,
                method=r["method"],
                path=r["path"],
                file_path=r["endpoint_file_path"],
                service_name=r["endpoint_service_name"],
                service_id=r["endpoint_service_id"],
            )

        caller_function_name = r["caller_function_name"]
        caller_id = f"caller:{r['caller_service_id']}:{r['caller_file_path']}:{caller_function_name}"
        if caller_id not in caller_nodes:
            caller_nodes[caller_id] = GraphNode(
                id=caller_id,
                node_type="caller",
                label=caller_function_name or "unknown",
                function_name=caller_function_name,
                method=None,
                path=None,
                file_path=r["caller_file_path"],
                service_name=r["caller_service_name"],
                service_id=r["caller_service_id"],
            )

        edges.append(GraphEdge(
            source=caller_id,
            target=ep_id,
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
        ))

    return GraphOut(
        nodes=list(endpoint_nodes.values()) + list(caller_nodes.values()),
        edges=edges,
        service_count=counts_row["service_count"],
        endpoint_count=counts_row["endpoint_count"],
    )
