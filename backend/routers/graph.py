from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()


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

            # All services tracked under this repo — the service-level graph nodes.
            service_rows = await conn.fetch(
                "SELECT id, name FROM services WHERE repo_id = $1 ORDER BY id",
                repo_id,
            )

            # Endpoints in this repo that have at least one consumer_edge —
            # these become the endpoint-level graph nodes. Filtered on the
            # endpoint owner's repo_id (s.repo_id).
            endpoint_rows = await conn.fetch(
                "SELECT DISTINCT e.id, e.method, e.path"
                " FROM endpoints e"
                " JOIN consumer_edges ce ON ce.endpoint_id = e.id"
                " JOIN services s ON s.id = e.service_id"
                " WHERE s.repo_id = $1"
                " ORDER BY e.id",
                repo_id,
            )

            # Consumer edges (caller service -> endpoint) for this repo.
            # Filtered on the caller's repo_id (cs.repo_id) rather than the
            # endpoint owner's — a consumer_edge is only ever created between
            # services discovered in the same analyze() run, so caller and
            # endpoint always share the same repo_id and either side of the
            # filter yields the same result set. This mirrors the endpoint
            # query's asymmetry intentionally, not a bug.
            edge_rows = await conn.fetch(
                "SELECT ce.caller_service_id, ce.endpoint_id,"
                " e.path AS endpoint_path, e.method AS endpoint_method,"
                " ce.call_count, ce.last_seen_at"
                " FROM consumer_edges ce"
                " JOIN endpoints e ON e.id = ce.endpoint_id"
                " JOIN services cs ON cs.id = ce.caller_service_id"
                " WHERE cs.repo_id = $1",
                repo_id,
            )

    service_nodes = [GraphNode(id=str(r["id"]), name=r["name"]) for r in service_rows]
    endpoint_nodes = [
        GraphNode(id=f"endpoint-{r['id']}", name=f"{r['method']} {r['path']}")
        for r in endpoint_rows
    ]
    nodes = service_nodes + endpoint_nodes

    edges = [
        GraphEdge(
            source=str(r["caller_service_id"]),
            target=f"endpoint-{r['endpoint_id']}",
            endpoint_path=r["endpoint_path"],
            endpoint_method=r["endpoint_method"],
            call_count=r["call_count"],
            last_seen_at=r["last_seen_at"],
        )
        for r in edge_rows
    ]
    return GraphOut(nodes=nodes, edges=edges)
