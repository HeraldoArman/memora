"""Parametrized Cypher strings for the knowledge graph.

Node labels: Person, Organization, Place, Object, Food, Event (from MemoryCategory).
Edges: RelationshipType values (WORKS_AT, LIKES, KNOWS, ...). All queries use $params
(bound by the driver) — never string-interpolate labels/relationships from user input.
Labels/relationships built per-call in repository.py are code constants (safe).

persistent_storage.md graph schema. Person is the hub; other entities attach via edges.
"""

from __future__ import annotations

# Upsert a Person. Two merge keys depending on caller intent:
#   - person_id provided → MERGE on person_id (caller's id is authoritative; a
#     re-register with a new id for the same name must update name, not silently
#     keep the old id — that detached face vectors from profiles).
#   - person_id absent (consolidator re-mention) → MERGE on name for cross-run
#     dedupe, stamping a fresh person_id on create.
UPSERT_PERSON_BY_ID = """
MERGE (p:Person {person_id: $person_id})
ON CREATE SET p.name = $name
SET p.name = $name,
    p.notes = coalesce($notes, p.notes),
    p.updated_at = datetime()
RETURN p.person_id AS person_id, p.name AS name, p.notes AS notes
"""

UPSERT_PERSON_BY_NAME = """
MERGE (p:Person {name: $name})
ON CREATE SET p.person_id = $person_id
SET p.notes = coalesce($notes, p.notes),
    p.updated_at = datetime()
RETURN p.person_id AS person_id, p.name AS name, p.notes AS notes
"""

# Kept for backward compatibility — merges on name only (the buggy path where a
# caller's explicit person_id was dropped on a name match). Prefer UPSERT_PERSON_BY_ID.
UPSERT_PERSON = UPSERT_PERSON_BY_NAME


def upsert_entity_cypher(label: str) -> str:
    """Return a MERGE for a `:{label}` node keyed by name. label is a code constant."""
    return f"""
MERGE (n:{label} {{name: $name}})
SET n.updated_at = datetime()
RETURN n.name AS name
"""


def add_relation_cypher(label: str, rel: str) -> str:
    """MERGE (p:Person {person_id})-[:rel]->(n:label {name}). rel/label are code constants."""
    return f"""
MATCH (p:Person {{person_id: $person_id}})
MERGE (n:{label} {{name: $name}})
MERGE (p)-[:{rel}]->(n)
RETURN n.name AS name
"""


# Get a person's profile + their outgoing relationships.
GET_PERSON = """
MATCH (p:Person {person_id: $person_id})
OPTIONAL MATCH (p)-[r]->(n)
RETURN p.person_id AS person_id, p.name AS name, p.notes AS notes,
       collect(DISTINCT {type: type(r), target: n.name, label: labels(n)[0]}) AS relationships
"""

# People directly connected to a given person (any direction, excluding self).
# name-keyed Person nodes have no person_id (NULL) — coalesce so they're not excluded.
RELATED_PEOPLE = """
MATCH (p:Person {person_id: $person_id})--(other:Person)
WHERE coalesce(other.person_id, '') <> $person_id
RETURN other.person_id AS person_id, other.name AS name
"""

# Search any entity by name substring (case-insensitive). Falls back to CONTAINS scan —
# ponytail: skip building a fulltext index for the hackathon; <1000 nodes.
SEARCH_ENTITY = """
MATCH (n)
WHERE n.name IS NOT NULL AND toLower(n.name) CONTAINS toLower($q)
RETURN labels(n)[0] AS label, n.name AS name, n.person_id AS person_id
LIMIT $limit
"""


# Subgraph within N hops of an entity name. $hops is an int literal (code constant).
# collect(DISTINCT m) keeps neighbor nodes in scope; rels is a list-of-lists (one per path)
# flattened in the RETURN via reduce. The center node n is always included (prepended to
# nodes) so an isolated entity with no relations still appears — callers can confirm it
# exists instead of seeing an empty graph indistinguishable from "not found".
def knowledge_graph_cypher(hops: int = 2) -> str:
    return f"""
MATCH (n)
WHERE n.name = $entity OR n.person_id = $entity
OPTIONAL MATCH path = (n)-[*1..{hops}]-(m)
WITH n, collect(DISTINCT m) AS nodes, collect(DISTINCT relationships(path)) AS rels
RETURN [x IN (nodes + [n]) | {{
  label: coalesce(labels(x)[0], labels(n)[0]),
  name: coalesce(x.name, n.name)
}}] AS nodes,
[rel IN reduce(acc = [], rl IN rels | acc + rl) | {{
  type: type(rel), from: startNode(rel).name, to: endNode(rel).name
}}] AS edges
"""


# Preferences: LIKES / DISLIKES edges from a person → Food/Preference nodes.
SEARCH_PREFERENCES = """
MATCH (p:Person {person_id: $person_id})-[:LIKES|DISLIKES]->(n)
RETURN n.name AS name, labels(n)[0] AS label,
       exists((p)-[:LIKES]->(n)) AS likes,
       exists((p)-[:DISLIKES]->(n)) AS dislikes
"""
