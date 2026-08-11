# Railway backend: build OK, deploy FAILED with empty logs

- **Date:** 2026-08-11
- **Service:** `backend` (FastAPI) — project `memora`, production env
- **Status:** RESOLVED (2026-08-11). Root cause: stale dashboard `preDeployCommand` not overridden by config-as-code.
- **Branch:** `develop`

## TL;DR

**Root cause found and fixed.** The `backend` service always FAILED deploy
with empty logs because a stale `preDeployCommand: ["cd packages/database &&
alembic upgrade head"]` was baked into the backend's **service settings**
(dashboard layer) from commit `aec549f`. That alembic predeploy runs in a
separate container before the app starts, hangs on `asyncpg`→Postgres TLS
connect (~60s), then fails. Per Railway semantics, a failed predeploy aborts
the deployment **before the app container starts** → deploy logs empty, status
FAILED.

Prior commits (`0bb0f51`, `6bc264b`) tried to fix this by editing
`apps/backend/railway.json` (removing predeploy, adding startCommand) — but
**config-as-code only overrides dashboard values for fields present in the
file**. The file _omitted_ `preDeployCommand`, so Railway kept the stale
dashboard value in the deployment manifest. Even clearing it via the API
(`serviceInstanceUpdate`) updated the service-instance record but the
deployment manifest still rendered the stale alembic command.

**The fix:** one line — explicitly set `"preDeployCommand": []` in
`apps/backend/railway.json` (commit `0f3a5c9`). The config file now forces the
field empty, overriding the stale dashboard value. Deploy `44b61454` →
**SUCCESS**, all 5 services green, `/health` 200, deploy logs populated.

**Follow-up (worker regression):** the worker and backend both pointed to
`apps/backend/railway.json`, so the backend's `startCommand` (uvicorn) was
overriding the worker's dashboard `startCommand` via config-as-code — the
worker was silently running the FastAPI backend instead of the LiveKit worker.
Fixed by adding a per-service `apps/backend/railway.worker.json` and repointing
the worker service's `configFile` to it (commit `fe632a3`). Worker deploy
`88a231a2` → SUCCESS, now runs `python -m workers.livekit_worker start`.

---

## System context

Monorepo (`HeraldoArman/memora`), uv workspace. Relevant layout:

```
apps/backend/            → FastAPI backend (the failing service)
  api/app.py             → create_app() factory (module import = app assembly)
  app.py                 → root entry: `from api.app import create_app; app = create_app()`
  api/routes/health.py   → GET /health pings Postgres + Neo4j + FAISS
  config/lifespan.py     → startup: settings → pg engine → neo4j driver → FAISS face repo
  config/logging.py      → setup_logging(); root handler → sys.stderr
  workers/livekit_worker.py → separate worker entrypoint
  Dockerfile             → two-stage (uv builder → python:3.12-slim-trixie runtime)
  railway.json           → shared config file (WARNING: also used by `worker`)
apps/dashboard/          → Next.js dashboard (deploys fine)
packages/database/       → SQLAlchemy models + alembic migrations (postgres/migrations)
packages/config/         → Settings (pydantic-settings), get_settings() lru_cached
```

Railway services (project `5f3f9f9f-8236-4f37-9576-74d2f33509dc`, prod env `873cc55c...`):

| Service   | ID                                     | Source / image                                                 |
| --------- | -------------------------------------- | -------------------------------------------------------------- |
| backend   | `8b0a94a8-9ec8-4548-9c4d-96bb25d80142` | GitHub repo, DOCKERFILE, `apps/backend/Dockerfile` — **FAILS** |
| worker    | `ef0b63a6-...`                         | same repo/image — **deploys fine**                             |
| dashboard | `9a4b8c3f-...`                         | GitHub repo, DOCKERFILE — **deploys fine**                     |
| neo4j     | `aa67ace9-...`                         | managed DB                                                     |
| Postgres  | `cdd96d2a-...`                         | managed DB (Railway "postgres-ssl" template)                   |

Backend service config (via Railway GraphQL `get-service-config`):

```json
{
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "apps/backend/Dockerfile"
  },
  "configFile": "apps/backend/railway.json",
  "deploy": {
    "healthcheckPath": "/health",
    "healthcheckTimeout": 60,
    "runtime": "V2",
    "useLegacyStacker": false,
    "multiRegionConfig": { "asia-southeast1-eqsg3a": { "numReplicas": 1 } }
  },
  "source": {
    "repo": "HeraldoArman/memora",
    "branch": "develop",
    "rootDirectory": "."
  }
}
```

**Verified 2026-08-11:** `rootDirectory` is `.` (repo root) and
`dockerfilePath` is `apps/backend/Dockerfile` **relative to repo root** — this is
correct, and the passing build confirms it. Building from the working directory
is NOT the problem.

### ⚠️ Stale config observation

When read via `get-service-config`, the stored service config showed:

```json
"preDeployCommand": ["cd packages/database && alembic upgrade head"]
```

This does **not** match the current `apps/backend/railway.json` (which has **no**
predeploy and **does** define a `startCommand`). The stored value also doesn't
match the fully-qualified predeploy from a later commit. So the "current" config
Railway reports appears **stale / desynced** from the committed `railway.json` —
worth treating config-as-code sync as unreliable until proven otherwise.

### ⚠️ Shared config file bug (worker regression)

`worker` and `backend` **both** use `configFile: apps/backend/railway.json`.
The `deploy.startCommand` we added for the backend (`uvicorn app:app ...`)
therefore **also overrides the worker's** dashboard-side start command
(`python -m workers.livekit_worker start`). The worker's latest deployment
(commit `0bb0f51`) returned SUCCESS — but it may now be silently running
**uvicorn, not the LiveKit worker**. Must verify before trusting the worker's
healthy status. Config should be per-service.

---

## The symptom, precisely

1. GitHub push to `develop` → Railway build starts.
2. Build (DOCKERFILE) **succeeds** every time.
3. Deploy phase **FAILS**, deployment status `FAILED`, instance status `REMOVED`.
4. Deploy/runtime logs are **EMPTY** — nothing at all. Not even a crash line.
5. Failure took roughly 60–180s in observed runs (varies).

This is the classic signature of a failure **before the container's process
actually starts** — e.g. a failing predeploy step, a platform-level
build→run handoff problem, or the container never being scheduled/started.

---

## What has been tried (chronological)

| Commit                                            | Change                                                                                                                     | Deploy result                                                                                                                                          |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ce1c8ce` `0476124` `ebecde2` `ff3f464` `42ed899` | SSL for postgres-ssl template; Docker cache-mount fixes (`s/` prefix + id)                                                 | Build goes green. Deploy still FAILs, logs empty.                                                                                                      |
| `cfc19ec`                                         | Added per-service `railway.json` config-as-code                                                                            | —                                                                                                                                                      |
| `aec549f`                                         | Added `deploy.preDeployCommand`: `cd packages/database && alembic upgrade head` (fully-qualified, absolute paths)          | Deploy `a7f4134c` FAILED, logs empty.                                                                                                                  |
| `6bc264b`                                         | Per forum advice: added explicit `deploy.startCommand` `uvicorn app:app --host 0.0.0.0 --port 8000 --app-dir apps/backend` | Deploy `00b6947f` FAILED, logs empty. GraphQL `meta.serviceManifest` confirmed both startCommand and preDeployCommand were **applied** to that deploy. |
| `0bb0f51`                                         | **Removed** predeploy entirely (hypothesis: alembic+asyncpg hung ~60s, matching ~90s failure duration)                     | Deploy `dab285bd` FAILED, logs **still empty**.                                                                                                        |

At the same commit (`0bb0f51`), `dashboard` redeployed **SUCCESS** and
`worker` redeployed **SUCCESS** — the platform/repo itself is healthy.

Failure via every permutation → config content is not the cause.

---

## Ruled OUT (with evidence)

Since the earlier commits we have proven the following are **NOT** the cause:

1. **The image or build output.** Build succeeds; the same image bytes run fine
   as the `worker` service.
2. **The app itself crashing at import.** Local test: import the exact app with
   the exact Railway env vars (`DATABASE_URL`, `LIVEKIT_*`, `GEMINI_API_KEY`,
   `NEO4J_*`) → module imports and `setup_logging()` prints
   `logging configured (level=INFO)`. The app boots.
3. **Predeploy command content.** Removing it entirely changed nothing.
4. **Start command content.** Aha — same `uvicorn app:app ... --app-dir
apps/backend` verified working locally against the image layout (WORKDIR
   `/app`, venv at `/app/.venv/bin`, `apps/backend/app.py` present). And the
   dashboard deploys fine with **no** start command and a `/` healthcheck — the
   same "Dockerfile + no startCommand" pattern we started from.
5. **Healthcheck pattern / `/health`.** Dashboard uses `/` and succeeds. Backend
   uses `/health` (which pings Postgres/Neo4j/FAISS and can 503). A failing
   healthcheck produces `CRASHED`/restart, not an empty-footprint FAILED —
   so unlikely, but still an open corner.
6. **Credentials / internal connectivity.** Postgres (`postgres.railway.internal:
5432/railway`) and Neo4j (`neo4j.railway.internal`) creds **match** the env
   that the backend runs with (verified against the Railway environment
   variables; secrets redacted here).
7. **Config values actually applying.** GraphQL `serviceManifest` for deploy
   `00b6947f` showed the startCommand/predeploy genuinely applied. (But note the
   stale-config observation above contradicts this for the _current_ stored
   config — needs re-verification.)

---

## Key Railway semantics learned

- **predeploy runs in a SEPARATE container.** If it fails, "the deployment does
  not proceed and the previous version keeps running" → deployment FAILED before
  the app container starts → **deploy logs empty**. (This is why the forum
  suggested a custom start command — to bypass a failing predeploy.)
- **Log severity tagging quirk:** our app's root logger writes to `sys.stderr`
  (see `config/logging.py`), so _every_ line — even INFO text — gets tagged
  `severity:error` in the Railway log UI. Don't read "error" as "crash".
- **Private hostnames** (`*.railway.internal`) only resolve inside Railway —
  confirmed unresolvable from a WSL host. Nothing to do locally.
- **Config-as-code vs dashboard:** Railway docs say code "always overrides"
  dashboard values, but our observed stored config appears stale — treat the
  commit on `develop` as source of truth and distrust the dashboard render.
- **startCommand working dir:** Railway runs the start command from the image
  (Dockerfile `WORKDIR /app`), so `--app-dir apps/backend` resolves — verified
  locally against the same layout.

---

## Resolved (2026-08-11)

| Commit    | Change                                                              | Deploy result                                                       |
| --------- | ------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `0f3a5c9` | Add `"preDeployCommand": []` to `apps/backend/railway.json`         | Deploy `44b61454` → **SUCCESS**. All 5 services green.              |
| `fe632a3` | Add `apps/backend/railway.worker.json`, repoint worker `configFile` | Worker deploy `88a231a2` → **SUCCESS** (runs LiveKit, not uvicorn). |

**The actual root cause** (the thing all prior attempts missed): the stale
`preDeployCommand` was in the **dashboard/service-settings layer**, and
Railway's config-as-code only overrides dashboard values for fields _present
in the file_. Omitting `preDeployCommand` from `railway.json` left the stale
dashboard value active in the deployment manifest. The `get-service-config`
API and the service-instance record both reported `preDeployCommand: []`
after the API clear, but the **deployment manifest** (what actually runs)
still rendered the stale alembic command — confirmed by reading
`deployment.meta.serviceManifest.deploy.preDeployCommand` via GraphQL. Only
adding the field explicitly to the config file overrode it.

---

## Earlier diagnostic writeup (kept for context)

---

## How to query Railway state (toolbox)

- MCP reads: `list-projects`, `list-services`, `get-service-config`,
  `get-status`, `list-deployments`, `get-logs`
  (`types: ["deploy","build","http"]`), `list-variables` (names only via OAuth).
- GraphQL fallback for details (serviceManifest/diagnosis):
  `https://backboard.railway.com/graphql/v2`, authenticated with
  `user.accessToken` from `~/.railway/config.json` (NOT `user.token`, which is
  null). Query deployments → `meta` (serviceManifest, resolved config) +
  `diagnosis` (null in all observed cases).
- Git branch to deploy from: `develop` (config: `source.branch`).

## Redaction note

No live secrets (DB passwords, API keys) are recorded in this doc. All
credential → config equivalences were verified against the Railway environment
directly. If this doc is converted to a public artifact, keep it redacted.
