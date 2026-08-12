# syntax=docker/dockerfile:1.7
# Build context = repo root (so bun can resolve the workspace + lockfile).
# Standalone output → runner needs no node_modules, just .next/standalone + static.

FROM oven/bun:1.3 AS deps
WORKDIR /app

# Cache deps: copy manifests + lockfile, install without source.
COPY package.json bun.lock pnpm-workspace.yaml ./
COPY apps/dashboard/package.json apps/dashboard/
RUN bun install --frozen-lockfile

# Copy source, rebuild with source present (standalone bundles its own deps).
COPY apps/dashboard apps/dashboard
RUN bun install --frozen-lockfile

FROM deps AS builder
WORKDIR /app/apps/dashboard
ENV NEXT_TELEMETRY_DISABLED=1
# Railway injects matching service vars as build args. rewrites() in next.config
# reads these at build time (standalone bakes them), so they must be present here,
# not just at runtime. See https://docs.railway.com/guides/build-time-vs-runtime-secrets
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
ARG NEXT_PUBLIC_LIVEKIT_URL
ENV NEXT_PUBLIC_LIVEKIT_URL=$NEXT_PUBLIC_LIVEKIT_URL
ARG NEXT_PUBLIC_WORKER_HEALTH_URL
ENV NEXT_PUBLIC_WORKER_HEALTH_URL=$NEXT_PUBLIC_WORKER_HEALTH_URL
RUN bun run build

# --- runner: minimal, no node_modules ---
FROM node:22-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app

# Non-root user
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

# Standalone server + static assets only.
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/static ./apps/dashboard/.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "apps/dashboard/server.js"]