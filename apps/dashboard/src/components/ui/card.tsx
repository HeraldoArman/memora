import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn("rounded-lg border border-ink-700 bg-ink-850/60 backdrop-blur-sm", className)}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-ink-700 px-5 py-3">
      <h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-ink-500">
        {title}
      </h3>
      {subtitle && <p className="mt-0.5 text-sm text-neutral-400">{subtitle}</p>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-5", className)}>{children}</div>;
}
