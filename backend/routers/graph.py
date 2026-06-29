from fastapi import APIRouter, Depends
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import GraphOut, GraphNode, GraphEdge

router = APIRouter()


@router.get("/graph", response_model=GraphOut)
async def get_graph(
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_context(conn, user_id)
            service_rows = await conn.fetch("SELECT id, name FROM services ORDER BY id")
            endpoint_rows = await conn.fetch(
                "SELECT DISTINCT e.id, e.method, e.path"
                " FROM endpoints e"
                " JOIN consumer_edges ce ON ce.endpoint_id = e.id"
                " ORDER BY e.id"
            )
            edge_rows = await conn.fetch(
                "SELECT ce.caller_service_id, ce.endpoint_id,"
                " e.path AS endpoint_path, e.method AS endpoint_method,"
                " ce.call_count, ce.last_seen_at"
                " FROM consumer_edges ce"
                " JOIN endpoints e ON e.id = ce.endpoint_id"
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
