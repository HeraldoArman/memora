import { cn } from "@/lib/cn";

type Variant = "default" | "ok" | "warn" | "crit" | "info";

const variants: Record<Variant, string> = {
  default: "border-accent-500/20 text-accent-500 bg-accent-500/10",
  ok: "border-ok-500/40 text-ok-400 bg-ok-500/10",
  warn: "border-warn-500/40 text-warn-400 bg-warn-500/10",
  crit: "border-crit-500/40 text-crit-400 bg-crit-500/10",
  info: "border-sky-500/40 text-sky-600 bg-sky-500/10",
};

export function Badge({
  variant = "default",
  children,
  className,
}: {
  variant?: Variant;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 font-mono text-xs font-medium",
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
