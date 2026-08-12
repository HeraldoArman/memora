# Step 2: Semantic Memory Retrieval — Verification

**Branch:** `refactor/agent-session-gemini`
**Date:** 2026-08-12
**Result:** ✅ Unit tests pass (390/390), lint clean, live verification pending

---

## What Was Done

Wire the ContextEngine into the agent so it retrieves known memories from Neo4j +
Postgres and injects them into the system prompt at connect time via
`Agent.update_instructions()`. The agent now knows facts without needing tool calls.

### Files changed

| File                                | Change                                                                                       |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| `packages/shared/prompts/system.py` | Added `{{context_package}}` placeholder + first-person glasses perspective prompt            |
| `reasoning/prompts/system.py`       | Restored `build_system_instruction()` replace logic                                          |
| `reasoning/agent/agent.py`          | Added `context_engine` param, `on_enter()` builds context → `update_instructions()`          |
| `gateway/livekit/entrypoint.py`     | Instantiate TextEmbedder + TextMemoryIndex + ContextEngine, wire into PipelineRunner + agent |
| `pipeline/runner.py`                | Accept `text_embedder` + `text_index` params, pass to Consolidator                           |
| `tests/unit/test_reasoning.py`      | 5 new tests: context injection, on_enter update_instructions, empty/no-engine paths          |

### Diff size

~50 lines production code, ~50 lines test code.

---

## How It Works

```
AgentSession.start()
  → MemoraAgent.on_enter()
    → _build_context_text()
      → CurrentContext(visible_people=[last_face.name])
      → ContextEngine.build(current)
        → Retriever.retrieve("", visible_people=["Asep"])
          → Neo4j: search_entity("Asep") → Person:Asep + relationships
          → Postgres: recent_memories() → episodic sessions
          → FAISS text index: (empty on first run, grows with new facts)
        → rank(candidates)
        → package(ranked, current) → ContextPackage
        → to_text(pkg) → "Fakta diketahui:\n- Asep\n- Sushi\n..."
    → build_system_instruction(text) → SYSTEM_INSTRUCTION with {{context_package}} replaced
    → self.update_instructions(instructions)
      → Gemini Realtime API: LiveClientContent (mid-session, no reconnect)
  → session.generate_reply("Sapa pengguna...")  → greeting
```

### Key design decisions

1. **Connect-time only, no per-turn RAG:** The `on_enter()` hook injects all known
   memories into the system prompt once. Per-turn RAG via `on_user_turn_completed`
   requires changing turn detection config (could break audio flow). The connect-time
   injection is sufficient — the agent has all known facts in its system prompt.

2. **`Agent.update_instructions()` for mid-session injection:** The LiveKit `Agent`
   class has `update_instructions()` which sends a mid-session instruction update to
   the Gemini Realtime API via `LiveClientContent`. No reconnect needed. This is the
   official LiveKit way to update the system prompt after session start.

3. **TextEmbedder + TextMemoryIndex wired but not bootstrapped:** The text index
   starts empty on first run. New facts from new conversations get embedded by the
   Consolidator (which now receives `text_embedder` + `text_index`). Old facts from
   Step 1 are in Neo4j (name-substring search still works). The text index is an
   enhancement for semantic similarity, not the primary retrieval path.

4. **First-person glasses perspective:** Updated system prompt to reflect that the
   agent sees through the user's glasses camera (first-person perspective) and hears
   through the microphone. This helps the model understand its embodiment.

5. **Graceful degradation:** If ContextEngine.build() fails (DB down, Gemini down),
   `on_enter()` catches the exception and keeps the static system prompt. The agent
   still works — it just doesn't have injected memories.

---

## Test Results

```
390 passed, 0 failed, 2 warnings in 16.15s
ruff check . → All checks passed!
ruff format --check . → 114 files already formatted
```

### New tests added

| Test                                      | Verifies                                                     |
| ----------------------------------------- | ------------------------------------------------------------ |
| `test_context_injected`                   | `build_system_instruction("Orang: Asep")` contains the text  |
| `test_empty_context_shows_fallback`       | Empty context shows "(belum ada konteks)"                    |
| `test_construct_with_context_engine`      | `MemoraAgent` stores `context_engine` param                  |
| `test_on_enter_calls_update_instructions` | `on_enter` calls `update_instructions` with context text     |
| `test_on_enter_skips_empty_context`       | `on_enter` skips `update_instructions` when context is empty |
| `test_on_enter_no_context_engine`         | `on_enter` still greets when no context engine wired         |

### Pre-existing tests updated

| Test                                   | Was testing                         | Now testing                    |
| -------------------------------------- | ----------------------------------- | ------------------------------ |
| `test_static_instruction`              | context_text ignored (bare-minimum) | context_text injected (Step 2) |
| `test_contains_face_identity_rules`    | unchanged                           | unchanged                      |
| `test_search_before_register_guidance` | unchanged                           | unchanged                      |

---

## Live Verification (pending)

### Test plan

1. Ensure Step 1 data exists (Person:Asep, LIKES→Sushi in Neo4j, facts in Postgres)
2. Start worker (with Postgres + Neo4j running)
3. Send prompt: "siapa Asep?" via data channel
4. Agent should answer "Asep suka sushi" (or similar) from the injected system prompt
5. No tool call needed — context is pre-injected
6. Check worker log: `on_enter: update_instructions with N chars context`

### What to look for in logs

```
on_enter: agent becoming active
on_enter: update_instructions with 250 chars context
on_enter: greeting generated
```

---

## What's Next

Step 3: Scene Understanding (fix Gemini Vision memory leak first) — agent knows
where it is. "Dimana aku?" → "Anda di apotek." Independent of Steps 1-2.
