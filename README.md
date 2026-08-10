# Memora

ESP32-S3 wearable AI memory device. Python + C++ monorepo: FastAPI backend (perception, memory, reasoning), ESP32-S3 firmware (camera, audio, LiveKit transport), shared data layers (Postgres, Neo4j, FAISS).

## Stack

- **Backend** — Python 3.12+, FastAPI, uvicorn
- **Firmware** — C++ / PlatformIO (ESP32-S3)
- **Databases** — Postgres 18 (relational), Neo4j 5 (memory graph), FAISS (vector search, in-process via `faiss-cpu`)
- **Package manager** — uv (Python), bun (JS tooling)
- **Monorepo** — Nx + `@nxlv/python` for task orchestration and caching
- **Lint/format** — Ruff (Python), Prettier (YAML/JSON/MD/TOML)
- **Git hooks** — Husky + lint-staged

## Prerequisites

- [uv](https://docs.astral.sh/uv/) >= 0.10
- [bun](https://bun.sh/) >= 1.3
- Docker (for Postgres/Neo4j via docker-compose)
- [PlatformIO](https://platformio.org/) CLI (firmware only, optional for backend-only dev)

## Getting Started

Install JS tooling + Python workspace:

```bash
bun install
uv sync
```

Start databases (Postgres + Neo4j):

```bash
bun run db:start
```

Run the backend dev server (FastAPI on <http://localhost:8000>):

```bash
bun run dev:backend
```

## Databases

| Service  | Port                     | Purpose                                      |
| -------- | ------------------------ | -------------------------------------------- |
| Postgres | 5432                     | Relational storage, repositories, migrations |
| Neo4j    | 7474 (HTTP), 7687 (Bolt) | Memory graph (semantic + episodic)           |
| FAISS    | —                        | In-process vector index (no container)       |

Default credentials: Postgres `postgres` / `password`, Neo4j `neo4j` / `memora`. Override via `POSTGRES_PASSWORD` and `NEO4J_PASSWORD` env vars.

Env file: `apps/backend/.env` (optional; docker-compose injects sensible defaults).

## Project Structure

```
memora/
├── apps/
│   ├── firmware/              # ESP32-S3 C++ firmware (PlatformIO)
│   │   ├── src/               # boot, camera, audio, display, button, livekit, network, power
│   │   ├── platformio.ini
│   │   └── main.cpp
│   └── backend/              # FastAPI backend
│       ├── api/              # routes, middleware, app.py
│       ├── gateway/          # livekit, websocket, session
│       ├── perception/       # face, speech, vision, observation, embeddings
│       ├── context/          # conversation context
│       ├── extraction/       # knowledge extraction
│       ├── pipeline/         # perception → memory orchestration
│       ├── memory/           # semantic, episodic, retrieval, ranking, graph
│       ├── reasoning/        # agent, prompts, session, response, planner
│       ├── tools/            # person, memory, reminder, calendar, observation, system
│       ├── services/         # cross-cutting services
│       ├── workers/          # background workers
│       └── config/           # backend-local config
├── packages/
│   ├── database/            # postgres (SQLAlchemy), neo4j, faiss layers
│   ├── shared/              # constants, dto, schemas, prompts, utils
│   └── config/             # railway, docker, env presets
├── models/                   # ML weights (gitignored): insightface, whisper
├── docs/                     # proposal, prd, appendix, diagrams, assets
├── scripts/                  # benchmark, seed, migrate, dev.py, deploy.py
└── .github/workflows/ci.yml  # lint, build, docker build
```

## Available Scripts

| Script                 | Description                               |
| ---------------------- | ----------------------------------------- |
| `bun run dev`          | Start all apps in dev mode (nx)           |
| `bun run dev:backend`  | Start FastAPI backend (uvicorn, reload)   |
| `bun run dev:firmware` | Build/watch firmware via PlatformIO       |
| `bun run build`        | Build all Python packages (nx)            |
| `bun run install:py`   | Sync all Python workspace members         |
| `bun run lint`         | Ruff check                                |
| `bun run lint:fix`     | Ruff check + autofix                      |
| `bun run format`       | Ruff format + Prettier write              |
| `bun run format:check` | Verify formatting (ruff + prettier)       |
| `bun run db:start`     | Start Postgres + Neo4j containers         |
| `bun run db:stop`      | Stop Postgres + Neo4j                     |
| `bun run db:down`      | Remove all containers                     |
| `bun run db:migrate`   | Run Alembic migrations (database package) |
| `bun run docker:build` | Build Docker Compose images               |
| `bun run docker:up`    | Build + start Docker Compose stack        |
| `bun run docker:down`  | Stop Docker Compose stack                 |
| `bun run docker:logs`  | Tail Docker Compose logs                  |

## Nx Targets

Python projects expose `install`, `build`, `dev`, `migrate` targets. Run across all:

```bash
bunx nx run-many -t build --exclude=tag:firmware
bunx nx run-many -t install
```

Per-project:

```bash
bunx nx build database
bunx nx dev backend
bunx nx migrate database
```

Firmware (`pio` commands via nx): `nx build firmware`, `nx upload firmware`, `nx monitor firmware`.

## CI

`.github/workflows/ci.yml` runs on push/PR to `main`/`master`:

1. **Lint & Format** — Ruff check + Ruff format check + Prettier check
2. **Build** — `uv sync --locked` + `nx run-many -t build` (excludes firmware)
3. **Docker Build** — Multi-stage uv Dockerfile for the backend image

Deployment is handled by Railway (no deploy workflow in-repo).

## Deployment

Docker Compose for local/full-stack:

```bash
bun run docker:up
bun run docker:logs
```

Production deploy via [Railway](https://railway.com).

## Git Hooks

Husky pre-commit runs lint-staged: Ruff fix + format on `.py`, Prettier on YAML/JSON/MD/TOML. Initialize with `bun run prepare` (runs automatically on `bun install`).
