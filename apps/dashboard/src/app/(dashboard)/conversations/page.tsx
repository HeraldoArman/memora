"use client";

import { useEffect, useState } from "react";
import { api, type Conversation, type Message } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export default function ConversationsPage() {
  const [sessions, setSessions] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);

  useEffect(() => {
    api
      .conversations(50)
      .then(setSessions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoadingMsgs(true);
    api
      .messages(selected.id)
      .then(setMessages)
      .catch(() => setMessages([]))
      .finally(() => setLoadingMsgs(false));
  }, [selected]);

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-neutral-900">Conversations</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Episodic memory — conversation sessions and transcripts.
        </p>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Session list */}
        <div className="w-80 shrink-0 overflow-y-auto scrollbar-thin">
          <Card>
            <CardHeader title="Sessions" />
            <CardBody className="space-y-1 p-2">
              {loading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-16 animate-pulse rounded-lg bg-ink-800" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <p className="py-8 text-center text-sm text-ink-500">No sessions yet.</p>
              ) : (
                sessions.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setSelected(s)}
                    className={cn(
                      "block w-full rounded-lg px-3 py-2 text-left transition-colors",
                      selected?.id === s.id
                        ? "bg-accent-500/10 text-accent-500"
                        : "hover:bg-ink-800",
                    )}
                  >
                    <p className="line-clamp-2 text-sm text-neutral-700">
                      {s.summary ?? "No summary"}
                    </p>
                    <p className="mt-1 font-mono text-xs text-ink-500">
                      {s.started_at ? new Date(s.started_at).toLocaleString() : "—"}
                    </p>
                  </button>
                ))
              )}
            </CardBody>
          </Card>
        </div>

        {/* Message view */}
        <div className="flex-1 overflow-hidden">
          <Card className="flex h-full flex-col">
            <CardHeader
              title="Transcript"
              subtitle={selected ? new Date(selected.started_at ?? "").toLocaleString() : undefined}
            />
            <CardBody className="flex-1 overflow-y-auto scrollbar-thin">
              {!selected ? (
                <p className="py-8 text-center text-sm text-ink-500">
                  Select a session to view messages.
                </p>
              ) : loadingMsgs ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-12 animate-pulse rounded-lg bg-ink-800" />
                  ))}
                </div>
              ) : messages.length === 0 ? (
                <p className="py-8 text-center text-sm text-ink-500">
                  No messages in this session.
                </p>
              ) : (
                <ul className="space-y-3">
                  {messages.map((m) => (
                    <li
                      key={m.id}
                      className={cn(
                        "max-w-[80%] rounded-lg px-4 py-2",
                        m.role === "user"
                          ? "ml-auto bg-accent-500/10 text-neutral-800"
                          : "bg-ink-800 text-neutral-700",
                      )}
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <Badge variant={m.role === "user" ? "info" : "default"}>{m.role}</Badge>
                      </div>
                      <p className="text-sm">{m.content}</p>
                      {m.created_at && (
                        <p className="mt-1 font-mono text-xs text-ink-500">
                          {new Date(m.created_at).toLocaleTimeString()}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
