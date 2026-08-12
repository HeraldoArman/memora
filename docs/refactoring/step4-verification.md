# Step 4 Verification — Proactive Planner

**Branch:** `refactor/agent-session-gemini`
**Date:** 2026-08-12

---

## What was wired

The `ProactivePlanner` (`reasoning/planner/planner.py`) was already fully
implemented with tests. Step 4 wires it into the agent lifecycle:

1. **`entrypoint.py`**: Instantiate `ProactivePlanner(reminder_service=...,
shopping_service=...)` from `tool_ctx` services. Pass `planner` to
   `MemoraAgent`. Stop planner in `finally` block alongside `session.aclose()`.

2. **`agent.py`**: Accept `planner` param in `__init__`. In `on_enter()`, after
   greeting, call `planner.start(self._get_context, self._on_proactive)`.
   `_get_context()` builds `CurrentContext` from `tool_ctx.last_face` +
   `tool_ctx.last_scene`. `_on_proactive(text)` calls
   `self.session.generate_reply(instructions=text)`.

### Design decisions

- **No `on_exit()` override**: LiveKit's `on_exit` fires only for agent
  workflows/handoffs. Single-agent setup may never trigger it. Planner cleanup
  happens in `entrypoint.py`'s `finally` block — the reliable teardown path.

- **No WorkingMemory/ObservationEngine**: `_get_context()` reads from
  `tool_ctx.last_face` + `tool_ctx.last_scene` dicts directly (same pattern as
  Steps 1-3). The planner takes a snapshot every 30s — it doesn't need a stream
  or fusion window.

- **No speech tracking**: The planner's "Siapa ini?" trigger needs
  `current.speech` to be non-empty. Without ObservationEngine, speech is always
  None → trigger won't fire. The system prompt already instructs the agent to
  ask "Siapa ini?" for unknown faces. See `docs/refactoring/future-plans.md`
  for the plan to add speech tracking.

---

## Files changed

| File                                         | Change                                                                            |
| -------------------------------------------- | --------------------------------------------------------------------------------- |
| `apps/backend/reasoning/agent/agent.py`      | `planner` param, `on_enter()` starts planner, `_get_context()`, `_on_proactive()` |
| `apps/backend/gateway/livekit/entrypoint.py` | Instantiate `ProactivePlanner`, pass to agent, stop in `finally`                  |
| `apps/backend/tests/unit/test_reasoning.py`  | 10 new tests in `TestProactivePlannerWiring` class                                |

## Diff size

~25 lines production, ~85 lines test

---

## Test results

```
342 passed, 1 warning in 4.93s
```

All tests pass, lint clean.

### New tests (10)

| Test                                     | What it verifies                                              |
| ---------------------------------------- | ------------------------------------------------------------- |
| `test_construct_with_planner`            | Agent accepts and stores `planner` param                      |
| `test_construct_no_planner`              | Agent works without planner (None)                            |
| `test_on_enter_starts_planner`           | `on_enter()` calls `planner.start(get_context, on_proactive)` |
| `test_on_enter_no_planner_no_crash`      | `on_enter()` doesn't crash when planner is None               |
| `test_get_context_none_when_empty`       | No face + no scene → returns None                             |
| `test_get_context_from_face_and_scene`   | Known face + scene → `CurrentContext` with name + location    |
| `test_get_context_unknown_face`          | Unknown face → `visible_people=["Orang tidak dikenali"]`      |
| `test_get_context_possible_match`        | Possible match → `visible_people=["Mungkin Budi"]`            |
| `test_get_context_scene_only_no_face`    | Scene only → empty `visible_people`, scene set                |
| `test_on_proactive_calls_generate_reply` | `_on_proactive(text)` calls `session.generate_reply`          |

---

## Live verification plan

1. Create a reminder: "ingatkan saya beli paracetamol" (agent calls `create_reminder`)
2. Point camera at a pharmacy/pharmacy-like scene
3. Wait 30s (planner interval)
4. Agent should proactively say: "Jangan lupa beli paracetamol"
5. Check worker log: `planner trigger: reminder=paracetamol location=apotek`

---

## What the planner does

Every 30s, the planner:

1. Calls `agent._get_context()` → builds `CurrentContext` from `tool_ctx`
2. Checks `_check_unknown_person()` — if unknown face + speech → "Siapa ini?" prompt
   (currently disabled — no speech tracking)
3. Checks pending reminders against scene location via keyword overlap
4. Checks shopping list items against scene location via keyword overlap
5. If a match is found (and cooldown has elapsed), calls `agent._on_proactive(text)`
6. `_on_proactive` calls `session.generate_reply(instructions=text)` — Gemini
   speaks the proactive reminder
7. Cooldown: each (item_id, location) pair only fires once per 5 min
