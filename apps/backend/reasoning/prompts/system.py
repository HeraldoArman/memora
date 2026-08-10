"""System instruction builder for the Gemini Live connection.

The base SYSTEM_INSTRUCTION (packages.shared.prompts.system) is immutable for the
connection lifetime (arch decision #2). At connect time we inject the initial context
package text into the {{context_package}} placeholder. Dynamic context thereafter
flows via tool-call results (agent calls current_scene/search_memory → fresh data),
NOT via the system prompt — so this is the only place the placeholder is filled.

Ponytail: a pure string-format function. No templating engine; the placeholder is a
literal {{context_package}} we str.replace.
"""

from __future__ import annotations

from prompts import SYSTEM_INSTRUCTION

_PLACEHOLDER = "{{context_package}}"


def build_system_instruction(context_text: str = "") -> str:
    """Inject the initial context package text into the system instruction.

    `context_text` is the rendered Bahasa text from context.to_text(pkg, activity=...).
    Empty string is valid — the agent will fetch context via tools on first turn.
    """
    return SYSTEM_INSTRUCTION.replace(_PLACEHOLDER, context_text or "(belum ada konteks)")


# --- self-check: placeholder replaced, idempotent, empty handled ---
def _self_check() -> None:  # pragma: no cover
    base = build_system_instruction("")
    assert _PLACEHOLDER not in base
    assert "(belum ada konteks)" in base
    filled = build_system_instruction("Orang: Asep. Lokasi: apotek.")
    assert "Asep" in filled and "apotek" in filled
    assert _PLACEHOLDER not in filled
    print("system prompt self-check OK: placeholder replaced, empty handled")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
