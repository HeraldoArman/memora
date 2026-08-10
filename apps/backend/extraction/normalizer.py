"""Normalizer — canonical-form rules for extracted entities.

knowledge_extraction.md §6: rule-first normalization (abbreviations, aliases, casing) with
LLM fallback only when ambiguous. The LLM already returns `canonical_name` when it can;
here we apply deterministic post-processing so "ui"/"UI"/"U.i." all map to the same node.
Ponytail: a small dict of Indonesian-common abbreviations covers the hackathon demo; the
graph MERGEs on the normalized name, so duplicates collapse automatically.
"""

from __future__ import annotations

import re

# Canonical expansions (lowercase keys). Indonesian institutions + common shortforms.
_CANONICAL: dict[str, str] = {
    "ui": "Universitas Indonesia",
    "ugm": "Universitas Gadjah Mada",
    "itb": "Institut Teknologi Bandung",
    "unpad": "Universitas Padjadjaran",
    "ktp": "Kartu Tanda Penduduk",
    "bpjs": "BPJS Kesehatan",
    "rs": "Rumah Sakit",
    "tokped": "Tokopedia",
    "gojek": "Gojek",
    "grab": "Grab",
}

# Title-case if no canonical mapping; keep ALL-CAPS acronyms as-is.
_ACRONYM = re.compile(r"^[A-Z]{2,}$")


def normalize(name: str) -> str:
    """Return the canonical form of `name`.

    1. Strip + collapse whitespace.
    2. Exact (case-insensitive) lookup in the canonical table.
    3. Else title-case, preserving ALL-CAPS acronyms (UI, KTP, BPJS).
    """
    if not name:
        return name
    cleaned = " ".join(name.split())
    key = cleaned.lower()
    if key in _CANONICAL:
        return _CANONICAL[key]
    if _ACRONYM.match(cleaned):
        return cleaned  # already an acronym
    return cleaned.title()


# --- self-check ---
def _self_check() -> None:  # pragma: no cover
    assert normalize("ui") == "Universitas Indonesia"
    assert normalize("UI") == "Universitas Indonesia"
    assert normalize("  tokped ") == "Tokopedia"
    assert normalize("KTP") == "Kartu Tanda Penduduk"
    assert normalize("asep") == "Asep"
    assert normalize("Muhammad Asep") == "Muhammad Asep"
    assert normalize("RS") == "Rumah Sakit"
    print("normalizer self-check OK")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
