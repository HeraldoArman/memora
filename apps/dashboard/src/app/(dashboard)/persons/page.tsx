"use client";

import { useEffect, useState } from "react";
import { api, type Person } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users } from "lucide-react";

export default function PersonsPage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .persons()
      .then(setPersons)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Persons</h1>
        <p className="mt-1 text-sm text-neutral-400">
          Face recognition registry — known people linked in the Neo4j graph.
        </p>
      </div>

      {error && (
        <Card>
          <CardBody>
            <p className="font-mono text-sm text-crit-400">{error}</p>
          </CardBody>
        </Card>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg bg-ink-800/50" />
          ))}
        </div>
      ) : persons.length === 0 ? (
        <Card>
          <CardBody>
            <div className="flex flex-col items-center gap-3 py-12">
              <Users className="size-10 text-ink-600" />
              <p className="text-sm text-ink-500">No persons registered yet.</p>
            </div>
          </CardBody>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {persons.map((p) => (
            <Card key={p.person_id ?? p.name}>
              <CardBody>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-lg font-medium text-neutral-100">{p.name}</p>
                    {p.person_id && (
                      <p className="mt-0.5 font-mono text-xs text-ink-500">{p.person_id}</p>
                    )}
                  </div>
                  <Badge variant={p.capture_count > 0 ? "ok" : "default"}>
                    {p.capture_count} captures
                  </Badge>
                </div>
                {p.notes && <p className="mt-2 text-sm text-neutral-400">{p.notes}</p>}
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
