"""Unit tests — parametrized Cypher builders (packages/database/graph/queries).

Assert the strings keep their structural guarantees: MERGE keys, label/relationship
interpolation points, param placeholders. (Real execution is covered by the DB
integration tests.)
"""

from __future__ import annotations

from graph.queries import (
    GET_PERSON,
    RELATED_PEOPLE,
    SEARCH_ENTITY,
    SEARCH_PREFERENCES,
    UPSERT_PERSON,
    add_relation_cypher,
    knowledge_graph_cypher,
    upsert_entity_cypher,
)


class TestStaticQueries:
    def test_upsert_person(self) -> None:
        assert "MERGE (p:Person {person_id: $person_id})" in UPSERT_PERSON
        assert "p.name = $name" in UPSERT_PERSON
        assert "updated_at" in UPSERT_PERSON

    def test_get_person_collects_relationships(self) -> None:
        assert "$person_id" in GET_PERSON
        assert "collect(DISTINCT" in GET_PERSON
        assert "type(r)" in GET_PERSON

    def test_related_people_excludes_self(self) -> None:
        assert "--(other:Person)" in RELATED_PEOPLE
        assert "$person_id" in RELATED_PEOPLE
        assert "coalesce(other.person_id" in RELATED_PEOPLE

    def test_search_entity_case_insensitive(self) -> None:
        assert "toLower(n.name) CONTAINS toLower($q)" in SEARCH_ENTITY
        assert "LIMIT $limit" in SEARCH_ENTITY

    def test_search_preferences(self) -> None:
        assert "-[:LIKES|DISLIKES]->" in SEARCH_PREFERENCES
        assert "$person_id" in SEARCH_PREFERENCES
        assert "exists((p)-[:LIKES]->(n))" in SEARCH_PREFERENCES


class TestQueryFactories:
    def test_upsert_entity_cypher(self) -> None:
        cypher = upsert_entity_cypher("Organization")
        assert "MERGE (n:Organization {name: $name})" in cypher

    def test_add_relation_cypher(self) -> None:
        cypher = add_relation_cypher("Food", "LIKES")
        assert "MATCH (p:Person {person_id: $person_id})" in cypher
        assert "MERGE (n:Food {name: $name})" in cypher
        assert "MERGE (p)-[:LIKES]->(n)" in cypher

    def test_knowledge_graph_cypher_hops(self) -> None:
        cypher = knowledge_graph_cypher(3)
        assert "[*1..3]" in cypher
        assert "collect(DISTINCT relationships(path))" in cypher
        assert "reduce(acc" in cypher
