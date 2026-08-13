export function ConnectionLog({ logs }: { logs: string[] }) {
  return (
    <section className="rounded-xl border border-ink-700 bg-ink-850 p-4 shadow-sm">
      <h2 className="mb-2 text-sm font-medium text-neutral-700">Log</h2>
      <pre className="h-48 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-xs text-neutral-300">
        {logs.join("\n")}
      </pre>
    </section>
  );
}
