type Status = "disconnected" | "connecting" | "connected" | "error";

const COLORS: Record<Status, string> = {
  connected: "bg-emerald-500",
  connecting: "bg-amber-400",
  error: "bg-red-500",
  disconnected: "bg-neutral-400",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${COLORS[status]}`} />
      <span className="text-neutral-700">{status}</span>
    </div>
  );
}

export type { Status };
