"use client";

import { useEffect, useState } from "react";
import { api, type HealthStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export function Header() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const h = await api.health();
        if (active) setHealth(h);
      } catch {
        // backend not up yet
      }
    };
    poll();
    const t = setInterval(poll, 10000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  const ok = health?.status === "ok";

  return (
    <header className="flex h-14 items-center justify-between border-b border-accent-500/20 bg-ink-900 px-6">
      <div className="flex items-center gap-3">
        <h1 className="font-mono text-sm font-semibold uppercase tracking-widest text-accent-500">
          Caregiver Dashboard
        </h1>
      </div>
      <div className="flex items-center gap-4">
        {health && (
          <div className="flex items-center gap-2 font-mono text-xs">
            <Badge variant={ok ? "ok" : "warn"}>
              <span
                className={`mr-1.5 size-1.5 rounded-full ${ok ? "bg-ok-500" : "bg-warn-500"}`}
              />
              {ok ? "All systems operational" : "Degraded"}
            </Badge>
            <span className="text-ink-500">
              PG:{health.postgres === "ok" ? "✓" : "✗"} · Neo4j:
              {health.neo4j === "ok" ? "✓" : "✗"} · FAISS:
              {health.faiss.startsWith("ok") ? "✓" : "✗"}
            </span>
          </div>
        )}
      </div>
    </header>
  );
}
