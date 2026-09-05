import asyncio

from fastapi import APIRouter, HTTPException, Query

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


@router.get("/players")
async def graph_players(
    team: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
):
    client = get_graph_client()
    return {
        "available": client.available(),
        "team": team,
        "players": await asyncio.to_thread(client.players, team, limit),
    }


@router.get("/players/{player_id}")
async def graph_player_profile(player_id: str):
    client = get_graph_client()
    profile = await asyncio.to_thread(client.player_profile, player_id)
    if client.available() and profile is None:
        raise HTTPException(status_code=404, detail="Player not found in the local graph")
    return {"available": client.available(), "profile": profile}


@router.get("/teams/compare")
async def graph_team_comparison(
    teams: str = Query(min_length=1, max_length=300),
):
    client = get_graph_client()
    requested = [item.strip() for item in teams.split(",") if item.strip()]
    comparison = await asyncio.to_thread(client.compare_teams, requested)
    return {"available": client.available(), **comparison}


@router.get("/teams/{team}/tactics")
async def graph_team_tactics(
    team: str,
    map_name: str | None = Query(default=None, max_length=64),
    side: str | None = Query(default=None, pattern="^(T|CT|t|ct)$"),
    opponent: str | None = Query(default=None, max_length=64),
):
    client = get_graph_client()
    profile = await asyncio.to_thread(
        client.team_tactics,
        team,
        map_name=map_name,
        side=side,
        opponent=opponent,
    )
    if client.available() and profile is None:
        raise HTTPException(status_code=404, detail="Team not found in the local graph")
    return {"available": client.available(), "profile": profile}


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
        "answer": client.coach_brief(q, evidence),
        "results": [item.as_dict() for item in evidence],
    }


@router.get("/round")
async def graph_round_detail(
    source_id: str = Query(min_length=1, max_length=200),
):
    client = get_graph_client()
    detail = await asyncio.to_thread(client.round_detail, source_id)
    if client.available() and detail is None:
        raise HTTPException(status_code=404, detail="Round source not found in the local graph")
    return {"available": client.available(), "detail": detail}


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
