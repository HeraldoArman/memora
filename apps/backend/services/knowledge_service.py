"""Knowledge service — entities, relationships, preferences in the Neo4j graph.

Wraps KnowledgeGraphRepo. Used by the extraction pipeline (write) + tools (read).
"""

from __future__ import annotations

from graph import repository as graph_repo


class KnowledgeService:
    def __init__(self, kg_repo: graph_repo.KnowledgeGraphRepo | None = None) -> None:
        self.kg_repo = kg_repo or graph_repo.KnowledgeGraphRepo()

    async def upsert_entity(self, *, name: str, category: str) -> dict:
        return await self.kg_repo.upsert_entity(name=name, category=category)

    async def add_relation(
        self, *, person_id: str, name: str, category: str, relationship: str
    ) -> dict:
        return await self.kg_repo.add_relation(
            person_id=person_id, name=name, category=category, relationship=relationship
        )

    async def search_entity(self, query: str) -> list[dict]:
        return await self.kg_repo.search_entity(query)

    async def entity_relationships(self, entity: str) -> dict:
        return await self.kg_repo.entity_relationships(entity)

    async def preferences(self, person_id: str) -> list[dict]:
        return await self.kg_repo.search_preferences(person_id)
