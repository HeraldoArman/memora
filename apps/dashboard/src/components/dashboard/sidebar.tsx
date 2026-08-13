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
    <aside className="flex h-full w-56 flex-col border-r border-accent-500/20 bg-gradient-to-b from-accent-500 to-accent-600">
      <div className="flex h-14 items-center gap-2 border-b border-white/10 px-5">
        <div className="size-6 rounded-lg bg-white" />
        <span className="font-mono text-sm font-bold tracking-widest text-white">MEMORA</span>
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
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-white text-accent-600"
                  : "text-white/80 hover:bg-white/10 hover:text-white",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-white/10 p-3">
        <div className="rounded-lg bg-white/10 px-3 py-2 font-mono text-xs text-white/70">
          v0.1.0 — caregiver
        </div>
      </div>
    </aside>
  );
}
