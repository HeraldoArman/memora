"use client";

import { useEffect, useState } from "react";
import { api, type HealthStatus, type Reminder, type Conversation } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Activity, AlertTriangle, CalendarClock, MessagesSquare } from "lucide-react";

export default function OverviewPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([api.health(), api.remindersToday(), api.conversations(5)]).then(
      ([h, r, c]) => {
        if (h.status === "fulfilled") setHealth(h.value);
        if (r.status === "fulfilled") setReminders(r.value);
        if (c.status === "fulfilled") setConversations(c.value);
        setLoading(false);
      },
    );
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">Overview</h1>
        <p className="mt-1 text-sm text-neutral-600">
          System status and recent activity for the patient.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Activity className="size-5 text-accent-500" />}
          label="Backend Status"
          value={
            health?.status === "ok"
              ? "Operational"
              : health?.status === "degraded"
                ? "Degraded"
                : "—"
          }
          variant={health?.status === "ok" ? "ok" : "warn"}
        />
        <StatCard
          icon={<CalendarClock className="size-5 text-sky-500" />}
          label="Reminders Today"
          value={String(reminders.length)}
        />
        <StatCard
          icon={<MessagesSquare className="size-5 text-violet-500" />}
          label="Recent Conversations"
          value={String(conversations.length)}
        />
        <StatCard
          icon={<AlertTriangle className="size-5 text-warn-500" />}
          label="Missed Reminders"
          value={String(reminders.filter((r) => !r.completed).length)}
          variant="warn"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Reminders */}
        <Card>
          <CardHeader title="Today's Reminders" />
          <CardBody>
            {loading ? (
              <Skeleton />
            ) : reminders.length === 0 ? (
              <Empty text="No reminders due today." />
            ) : (
              <ul className="space-y-2">
                {reminders.map((r) => (
                  <li
                    key={r.reminder_id}
                    className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2"
                  >
                    <span className="text-sm text-neutral-800">{r.title}</span>
                    <Badge variant={r.completed ? "ok" : "warn"}>
                      {r.completed ? "done" : "pending"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {/* Recent conversations */}
        <Card>
          <CardHeader title="Recent Conversations" />
          <CardBody>
            {loading ? (
              <Skeleton />
            ) : conversations.length === 0 ? (
              <Empty text="No conversations yet." />
            ) : (
              <ul className="space-y-2">
                {conversations.map((c) => (
                  <li key={c.id} className="rounded-lg bg-ink-800 px-3 py-2">
                    <p className="text-sm text-neutral-700">{c.summary ?? "No summary"}</p>
                    <p className="mt-0.5 font-mono text-xs text-ink-500">
                      {c.started_at ? new Date(c.started_at).toLocaleString() : "—"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  variant = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  variant?: "default" | "ok" | "warn";
}) {
  return (
    <Card>
      <CardBody className="flex items-center gap-4">
        <div className="flex size-10 items-center justify-center rounded-lg bg-accent-500/10">
          {icon}
        </div>
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-ink-500">{label}</p>
          <p className="mt-0.5 text-xl font-semibold text-neutral-900">{value}</p>
        </div>
      </CardBody>
    </Card>
  );
}

function Skeleton() {
  return <div className="h-24 animate-pulse rounded-lg bg-ink-800" />;
}

function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-ink-500">{text}</p>;
}
