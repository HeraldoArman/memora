"""Neo4j repositories — PersonRepo + KnowledgeGraphRepo.

Wrap the async driver + parametrized Cypher. Return plain dicts to keep the graph layer
decoupled from Pydantic DTOs (callers map dict→DTO). Code-constant labels/relationships are
mapped from MemoryCategory/RelationshipType — never from user input.
"""

from __future__ import annotations

from graph import client as neo4j_client
from graph import queries

# MemoryCategory → Neo4j node label. Person is handled separately (hub node).
_ENTITY_LABELS = {
    "Organization": "Organization",
    "Place": "Place",
    "Object": "Object",
    "Food": "Food",
    "Event": "Event",
    "Preference": "Preference",  # stored as its own label for preference memories
}


def _label_for_category(category: str) -> str:
    return _ENTITY_LABELS.get(category, category)


class PersonRepo:
    """CRUD for Person nodes (the hub of the graph)."""

    async def upsert_person(
        self, *, person_id: str | None = None, name: str, notes: str | None = None
    ) -> dict:
        """MERGE on person_id when given (caller-authoritative id), else on name
        (consolidator dedupe-by-name). Returning the node lets the caller thread
        the resolved person_id into subsequent relation calls."""
        from utils.time_ids import gen_id

        async with neo4j_client.get_driver().session() as s:
            if person_id is not None:
                rec = await s.execute_write(
                    _upsert_person_by_id_tx, person_id=person_id, name=name, notes=notes
                )
            else:
                rec = await s.execute_write(
                    _upsert_person_by_name_tx,
                    person_id=gen_id(),
                    name=name,
                    notes=notes,
                )
            return dict(rec) if rec else {}

    async def get_person(self, person_id: str) -> dict | None:
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(_get_person_tx, person_id=person_id)
            return dict(result[0]) if result else None

    async def related_people(self, person_id: str) -> list[dict]:
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(_related_people_tx, person_id=person_id)
            return [dict(r) for r in result]


class KnowledgeGraphRepo:
    """Entity + relationship operations on the knowledge graph."""

    async def upsert_entity(self, *, name: str, category: str) -> dict:
        cypher = queries.upsert_entity_cypher(_label_for_category(category))
        async with neo4j_client.get_driver().session() as s:
            rec = await s.execute_write(_run_tx, cypher=cypher, name=name)
            return dict(rec) if rec else {}

    async def add_relation(
        self, *, person_id: str, name: str, category: str, relationship: str
    ) -> dict:
        cypher = queries.add_relation_cypher(_label_for_category(category), relationship)
        async with neo4j_client.get_driver().session() as s:
            rec = await s.execute_write(_run_tx, cypher=cypher, person_id=person_id, name=name)
            return dict(rec) if rec else {}

    async def search_entity(self, query: str, limit: int = 10) -> list[dict]:
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(_search_entity_tx, q=query, limit=limit)
            return [dict(r) for r in result]

    async def list_people(self, limit: int = 100) -> list[dict]:
        """Return Person nodes without sharing the general entity-search cap."""
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(_list_people_tx, limit=limit)
            return [dict(r) for r in result]

    async def entity_relationships(self, entity: str) -> dict:
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(
                _knowledge_graph_tx, entity=entity, cypher=queries.knowledge_graph_cypher()
            )
            return dict(result[0]) if result else {"nodes": [], "edges": []}

    async def search_preferences(self, person_id: str) -> list[dict]:
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(
                _run_read_tx, cypher=queries.SEARCH_PREFERENCES, person_id=person_id
            )
            return [dict(r) for r in result]

    async def full_graph(self) -> dict:
        """Return every node + edge in the graph. Used by the dashboard viz."""
        async with neo4j_client.get_driver().session() as s:
            result = await s.execute_read(_run_read_tx, cypher=queries.FULL_GRAPH)
            if not result:
                return {"nodes": [], "edges": []}
            rec = dict(result[0])
            # Filter out null edges (from OPTIONAL MATCH on isolated nodes)
            rec["edges"] = [e for e in rec.get("edges", []) if e.get("type") is not None]
            return rec


# --- tx functions (run inside driver sessions) ---


async def _upsert_person_by_id_tx(tx, *, person_id, name, notes):
    result = await tx.run(queries.UPSERT_PERSON_BY_ID, person_id=person_id, name=name, notes=notes)
    rec = await result.single()
    return rec


async def _upsert_person_by_name_tx(tx, *, person_id, name, notes):
    result = await tx.run(
        queries.UPSERT_PERSON_BY_NAME, person_id=person_id, name=name, notes=notes
    )
    rec = await result.single()
    return rec


async def _get_person_tx(tx, *, person_id):
    result = await tx.run(queries.GET_PERSON, person_id=person_id)
    return [r async for r in result]


async def _related_people_tx(tx, *, person_id):
    result = await tx.run(queries.RELATED_PEOPLE, person_id=person_id)
    return [r async for r in result]


async def _run_tx(tx, *, cypher, **params):
    result = await tx.run(cypher, **params)
    rec = await result.single()
    return rec


async def _run_read_tx(tx, *, cypher, **params):
    result = await tx.run(cypher, **params)
    return [r async for r in result]


async def _search_entity_tx(tx, *, q, limit):
    result = await tx.run(queries.SEARCH_ENTITY, q=q, limit=limit)
    return [r async for r in result]


async def _list_people_tx(tx, *, limit):
    result = await tx.run(queries.LIST_PEOPLE, limit=limit)
    return [r async for r in result]


async def _knowledge_graph_tx(tx, *, entity, cypher):
    result = await tx.run(cypher, entity=entity)
    return [r async for r in result]
