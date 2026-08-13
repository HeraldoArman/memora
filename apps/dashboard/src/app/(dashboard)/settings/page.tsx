"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">Settings</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Runtime key-value configuration from Postgres.
        </p>
      </div>

      <Card>
        <CardHeader title="Configuration" subtitle={`${Object.keys(settings).length} key(s)`} />
        <CardBody>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-lg bg-ink-800" />
              ))}
            </div>
          ) : Object.keys(settings).length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-500">No settings configured.</p>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-ink-700">
                  <th className="px-3 py-2 text-left font-mono text-xs uppercase tracking-widest text-ink-500">
                    Key
                  </th>
                  <th className="px-3 py-2 text-left font-mono text-xs uppercase tracking-widest text-ink-500">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(settings).map(([key, value]) => (
                  <tr key={key} className="border-b border-ink-700 last:border-0">
                    <td className="px-3 py-2">
                      <Badge variant="info">{key}</Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-sm text-neutral-700">{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
