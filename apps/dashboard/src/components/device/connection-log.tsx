export function ConnectionLog({ logs }: { logs: string[] }) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-2 text-sm font-medium text-neutral-300">Log</h2>
      <pre className="h-48 overflow-auto rounded-lg bg-black p-3 font-mono text-xs text-neutral-400">
        {logs.join("\n")}
      </pre>
    </section>
  );
}
