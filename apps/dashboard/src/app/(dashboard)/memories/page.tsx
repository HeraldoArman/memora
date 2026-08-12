"use client";

import { useEffect, useState } from "react";
import { api, type Memory } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function MemoriesPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .memories(100)
      .then(setMemories)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Memories</h1>
        <p className="mt-1 text-sm text-neutral-400">
          Extracted facts from conversations — the relational long-term store.
        </p>
      </div>

      {error && (
        <Card>
          <CardBody>
            <p className="font-mono text-sm text-crit-400">{error}</p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Recent Facts" subtitle={`${memories.length} fact(s)`} />
        <CardBody>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-md bg-ink-800/50" />
              ))}
            </div>
          ) : memories.length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-500">No memories extracted yet.</p>
          ) : (
            <ul className="space-y-2">
              {memories.map((m) => (
                <li key={m.id} className="rounded-md border border-ink-700 bg-ink-800/30 px-4 py-3">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm text-neutral-200">{m.fact}</p>
                    <div className="flex shrink-0 items-center gap-2">
                      {m.category && <Badge variant="info">{m.category}</Badge>}
                      {m.confidence != null && (
                        <Badge
                          variant={
                            m.confidence >= 0.8 ? "ok" : m.confidence >= 0.5 ? "warn" : "crit"
                          }
                        >
                          {Math.round(m.confidence * 100)}%
                        </Badge>
                      )}
                    </div>
                  </div>
                  {m.created_at && (
                    <p className="mt-1.5 font-mono text-xs text-ink-500">
                      {new Date(m.created_at).toLocaleString()}
                      {m.person_id ? ` · ${m.person_id}` : ""}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
