"use client";

import { useEffect, useState } from "react";
import { api, type Reminder, type Event } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export default function RemindersPage() {
  const [today, setToday] = useState<Reminder[]>([]);
  const [upcoming, setUpcoming] = useState<Reminder[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      api.remindersToday(),
      api.remindersUpcoming(20),
      api.eventsUpcoming(20),
    ]).then(([t, u, e]) => {
      if (t.status === "fulfilled") setToday(t.value);
      if (u.status === "fulfilled") setUpcoming(u.value);
      if (e.status === "fulfilled") setEvents(e.value);
      setLoading(false);
    });
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">Reminders & Events</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Today's reminders, upcoming tasks, and calendar events.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Today's reminders */}
        <Card>
          <CardHeader title="Today" subtitle={`${today.length} reminder(s)`} />
          <CardBody>
            {loading ? (
              <Skeleton />
            ) : today.length === 0 ? (
              <Empty text="No reminders due today." />
            ) : (
              <ul className="space-y-2">
                {today.map((r) => (
                  <li
                    key={r.reminder_id}
                    className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2"
                  >
                    <div>
                      <p className="text-sm text-neutral-800">{r.title}</p>
                      {r.note && <p className="text-xs text-ink-500">{r.note}</p>}
                      {r.due_at && (
                        <p className="mt-0.5 font-mono text-xs text-ink-500">
                          {new Date(r.due_at).toLocaleTimeString()}
                        </p>
                      )}
                    </div>
                    <Badge variant={r.completed ? "ok" : "warn"}>
                      {r.completed ? "done" : "pending"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {/* Upcoming reminders */}
        <Card>
          <CardHeader title="Upcoming Reminders" subtitle={`${upcoming.length} item(s)`} />
          <CardBody>
            {loading ? (
              <Skeleton />
            ) : upcoming.length === 0 ? (
              <Empty text="No upcoming reminders." />
            ) : (
              <ul className="space-y-2">
                {upcoming.map((r) => (
                  <li key={r.reminder_id} className="rounded-lg bg-ink-800 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-neutral-800">{r.title}</p>
                      {r.due_at && (
                        <span className="font-mono text-xs text-ink-500">
                          {new Date(r.due_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    {r.note && <p className="text-xs text-ink-500">{r.note}</p>}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {/* Calendar events */}
        <Card>
          <CardHeader title="Upcoming Events" subtitle={`${events.length} event(s)`} />
          <CardBody>
            {loading ? (
              <Skeleton />
            ) : events.length === 0 ? (
              <Empty text="No upcoming events." />
            ) : (
              <ul className="space-y-2">
                {events.map((e) => (
                  <li key={e.event_id} className="rounded-lg bg-ink-800 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-neutral-800">{e.title}</p>
                      {e.starts_at && (
                        <span className="font-mono text-xs text-ink-500">
                          {new Date(e.starts_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    {e.location && <p className="mt-0.5 text-xs text-ink-500">📍 {e.location}</p>}
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

function Skeleton() {
  return <div className="h-24 animate-pulse rounded-lg bg-ink-800" />;
}

function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-ink-500">{text}</p>;
}
