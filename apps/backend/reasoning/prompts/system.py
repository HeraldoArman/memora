"""System instruction builder for the Gemini Live connection.

Step 2: the {{context_package}} placeholder is replaced with context_text from
ContextEngine.build(). Falls back to "(belum ada konteks)" when empty.
"""

from __future__ import annotations

from prompts import SYSTEM_INSTRUCTION


def build_system_instruction(context_text: str = "") -> str:
    """Return the system instruction with context_text injected into {{context_package}}."""
    return SYSTEM_INSTRUCTION.replace("{{context_package}}", context_text or "(belum ada konteks)")


# --- self-check: placeholder replace works ---
def _self_check() -> None:  # pragma: no cover
    base = build_system_instruction("")
    assert "(belum ada konteks)" in base, "empty context should show fallback"
    filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
    assert "Orang: Asep" in filled, "context_text should appear in filled instruction"
    assert "{{context_package}}" not in filled, "placeholder must be replaced"
    assert "Memora" in base
    print("system prompt self-check OK: placeholder replace works")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
