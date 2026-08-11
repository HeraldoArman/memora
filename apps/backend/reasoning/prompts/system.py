"""System instruction builder for the Gemini Live connection.

refactor/bare-minimum: the system prompt is static (no {{context_package}} placeholder).
context_text is accepted for API compatibility but ignored. Re-enable the placeholder
by adding {{context_package}} back to SYSTEM_INSTRUCTION and restoring the replace logic.
"""

from __future__ import annotations

from prompts import SYSTEM_INSTRUCTION


def build_system_instruction(context_text: str = "") -> str:
    """Return the system instruction. context_text is ignored in bare-minimum."""
    return SYSTEM_INSTRUCTION


# --- self-check: returns the static system instruction ---
def _self_check() -> None:  # pragma: no cover
    base = build_system_instruction("")
    filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
    assert base == filled, "bare-minimum: context_text is ignored"
    assert "Memora" in base
    print("system prompt self-check OK: static instruction returned")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
