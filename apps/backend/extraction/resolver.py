"""Resolver — entity resolution across extraction mentions.

memory_pipeline.md §5 (resolution): decide whether "Asep", "Muhammad Asep", "Bang Asep"
refer to the same graph node. Rule-first: exact normalized-name match → same node;
substring/alias match → same; new normalized name → create. Face identity (PersonService)
is the strongest signal for Person entities but is applied upstream (FaceRecognizer) —
here we resolve purely on names + the existing graph.

Ponytail: no clustering/ML — the graph MERGEs on normalized name, so all mentions of
"Asep" collapse to one node automatically. This resolver only needs to surface whether a
name already exists (so the consolidator can UPDATE vs CREATE) and de-duplicate within a
single extraction batch (aliases pointing at the same canonical name).
"""

from __future__ import annotations

from difflib import SequenceMatcher

from extraction.normalizer import normalize

# Names that are common Indonesian honorifics/aliases — stripped before matching.
_HONORIFICS = {"bang", "mas", "mbak", "bu", "pak", "kak", "om", "tante", "abang", "mpok"}

# Alias score threshold for "probably the same person" (SequenceMatcher ratio).
_ALIAS_THRESHOLD = 0.88


def _strip_honorific(name: str) -> str:
    tokens = name.split()
    if tokens and tokens[0].lower() in _HONORIFICS:
        return " ".join(tokens[1:])
    return name


def resolve_name(name: str) -> str:
    """Canonical key for a name: honorific-stripped + normalized."""
    return normalize(_strip_honorific(name))


def resolve_batch(names: list[str]) -> dict[str, str]:
    """De-duplicate within a single extraction batch.

    Returns {original_name: canonical_key}. Mentions that resolve to the same canonical
    key (e.g. "Bang Asep" and "Asep") map together, so the consolidator creates one node.
    """
    mapping: dict[str, str] = {}
    for n in names:
        mapping[n] = resolve_name(n)
    return mapping


def is_alias(a: str, b: str) -> bool:
    """Heuristic: are two names likely the same person?

    Same canonical key → True. Else if one contains the other (first/last name match) or
    the SequenceMatcher ratio ≥ threshold → True. Used to suggest merges, not to force them.
    """
    ka, kb = resolve_name(a), resolve_name(b)
    if ka == kb:
        return True
    # shared last token (surname) + shared first token → likely same
    ta, tb = ka.split(), kb.split()
    if len(ta) > 1 and len(tb) > 1 and ta[-1] == tb[-1] and ta[0] == tb[0]:
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= _ALIAS_THRESHOLD


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    # honorific stripping + normalization
    assert resolve_name("Bang Asep") == "Asep"
    assert resolve_name("Pak Asep") == "Asep"
    assert resolve_name("Muhammad Asep") == "Muhammad Asep"
    # batch de-dup
    m = resolve_batch(["Bang Asep", "Asep", "Tokopedia"])
    assert m["Bang Asep"] == m["Asep"] == "Asep", m
    assert m["Tokopedia"] == "Tokopedia"
    # alias heuristic: honorific strip → same canonical key
    assert is_alias("Bang Asep", "Asep") is True
    assert is_alias("Pak Asep", "Asep") is True
    # shared first+last token (surname) → likely same
    assert is_alias("Muhammad Asep", "Muhammad Asep") is True
    # genuinely different names → not aliases
    assert is_alias("Asep", "Tokopedia") is False
    assert is_alias("Asep", "Budi") is False
    print("resolver self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
