export function AgentDisplay({ text }: { text: string }) {
  return (
    <section className="rounded-xl border border-ink-700 bg-ink-850 p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-medium text-neutral-700">Agent display (OLED)</h2>
      <div className="min-h-32 rounded-lg border border-ink-700 bg-black p-3">
        <pre className="whitespace-pre-wrap break-words font-mono text-sm text-emerald-300">
          {text || "—"}
        </pre>
      </div>
    </section>
  );
}
