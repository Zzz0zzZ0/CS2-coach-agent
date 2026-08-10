from fastapi import APIRouter, Query

from app.core.providers import get_graph_client

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/stats")
async def graph_stats():
    client = get_graph_client()
    return {"available": client.available(), **client.stats()}


@router.get("/maps")
async def graph_maps():
    client = get_graph_client()
    return {"available": client.available(), "maps": client.maps()}


@router.get("/search")
async def graph_search(
    q: str = Query(min_length=1, max_length=500),
    map_name: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=6, ge=1, le=20),
):
    client = get_graph_client()
    evidence = await client.retrieve(
        q,
        metadata_filter={"map": map_name} if map_name else {},
        k=limit,
        global_search=True,
    ) if client.available() else []
    return {
        "available": client.available(),
        "query": q,
        "results": [item.as_dict() for item in evidence],
    }


@router.get("/subgraph")
async def graph_subgraph(
    map_name: str | None = Query(default=None, max_length=64),
    limit_nodes: int = Query(default=64, ge=8, le=160),
    limit_edges: int = Query(default=120, ge=8, le=300),
):
    client = get_graph_client()
    if not client.available():
        return {"available": False, "nodes": [], "edges": []}
    return {"available": True, **client.subgraph(map_name, limit_nodes, limit_edges)}
