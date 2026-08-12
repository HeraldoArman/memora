"""Unit tests — FULL_GRAPH Cypher query + KnowledgeGraphRepo.full_graph.

Assert the query string keeps its structural guarantees and that
full_graph() filters null edges from the OPTIONAL MATCH.
"""

from __future__ import annotations

from graph.queries import FULL_GRAPH


class TestFullGraphQuery:
    def test_collects_nodes_and_edges(self) -> None:
        assert "MATCH (n)" in FULL_GRAPH
        assert "OPTIONAL MATCH (n)-[r]->(m)" in FULL_GRAPH
        assert "collect(DISTINCT" in FULL_GRAPH

    def test_node_shape(self) -> None:
        assert "label: labels(n)[0]" in FULL_GRAPH
        assert "name: n.name" in FULL_GRAPH
        assert "person_id: n.person_id" in FULL_GRAPH

    def test_edge_shape(self) -> None:
        assert "type: type(r)" in FULL_GRAPH
        assert "from: startNode(r).name" in FULL_GRAPH
        assert "to: endNode(r).name" in FULL_GRAPH

    def test_has_limit(self) -> None:
        assert "LIMIT 500" in FULL_GRAPH


class _FakeSession:
    """Async context manager that returns fake records from execute_read."""

    def __init__(self, records: list):
        self._records = records

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute_read(self, fn, *, cypher, **kw):
        return self._records


class _FakeDriver:
    def __init__(self, records: list):
        self._session = _FakeSession(records)

    def session(self):
        return self._session


class _FakeRec(dict):
    """Mimics a Neo4j Record — dict subclass so dict(rec) works."""

    pass


class TestFullGraphRepoFiltersNullEdges:
    async def test_filters_null_edges(self) -> None:
        """full_graph() should drop edges where type is None (from OPTIONAL MATCH
        on isolated nodes that have no outgoing relationships)."""
        from graph import repository as graph_repo

        fake_record = _FakeRec(
            {
                "nodes": [
                    {"label": "Person", "name": "Asep", "person_id": "per-1"},
                    {"label": "Place", "name": "Jakarta", "person_id": None},
                ],
                "edges": [
                    {"type": "LIVES_IN", "from": "Asep", "to": "Jakarta"},
                    {"type": None, "from": None, "to": None},  # null from OPTIONAL MATCH
                ],
            }
        )

        original = graph_repo.neo4j_client.get_driver
        graph_repo.neo4j_client.get_driver = lambda: _FakeDriver([fake_record])
        try:
            repo = graph_repo.KnowledgeGraphRepo()
            result = await repo.full_graph()
        finally:
            graph_repo.neo4j_client.get_driver = original

        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["name"] == "Asep"
        assert len(result["edges"]) == 1  # null edge filtered out
        assert result["edges"][0]["type"] == "LIVES_IN"

    async def test_empty_graph_returns_empty(self) -> None:
        from graph import repository as graph_repo

        original = graph_repo.neo4j_client.get_driver
        graph_repo.neo4j_client.get_driver = lambda: _FakeDriver([])  # no records
        try:
            repo = graph_repo.KnowledgeGraphRepo()
            result = await repo.full_graph()
        finally:
            graph_repo.neo4j_client.get_driver = original

        assert result == {"nodes": [], "edges": []}
