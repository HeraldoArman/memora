"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Brain,
  CalendarClock,
  Glasses,
  LayoutDashboard,
  MessagesSquare,
  Settings,
  Users,
} from "lucide-react";
import { cn } from "@/lib/cn";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/knowledge-graph", label: "Knowledge Graph", icon: Brain },
  { href: "/memories", label: "Memories", icon: Activity },
  { href: "/conversations", label: "Conversations", icon: MessagesSquare },
  { href: "/persons", label: "Persons", icon: Users },
  { href: "/reminders", label: "Reminders", icon: CalendarClock },
  { href: "/debugging", label: "Device Harness", icon: Glasses },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 flex-col border-r border-ink-700 bg-ink-900">
      <div className="flex h-14 items-center gap-2 border-b border-ink-700 px-5">
        <div className="size-6 rounded bg-accent-500" />
        <span className="font-mono text-sm font-bold tracking-widest">MEMORA</span>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {nav.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-ink-800 text-accent-400"
                  : "text-neutral-400 hover:bg-ink-800/50 hover:text-neutral-100",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-ink-700 p-3">
        <div className="rounded-md bg-ink-850 px-3 py-2 font-mono text-xs text-ink-500">
          v0.1.0 — caregiver
        </div>
      </div>
    </aside>
  );
}
