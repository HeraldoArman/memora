"""Graph endpoint — full Neo4j knowledge graph for the force-directed viz."""

from __future__ import annotations

from fastapi import APIRouter
from graph import repository as graph_repo

router = APIRouter()


@router.get("/graph")
async def get_graph() -> dict:
    """Return all nodes + edges in the knowledge graph."""
    return await graph_repo.KnowledgeGraphRepo().full_graph()
