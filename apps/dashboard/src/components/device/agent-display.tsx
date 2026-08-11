export function AgentDisplay({ text }: { text: string }) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-300">Agent display (OLED)</h2>
      <div className="min-h-32 rounded-lg border border-neutral-800 bg-black p-3">
        <pre className="whitespace-pre-wrap break-words font-mono text-sm text-emerald-300">
          {text || "—"}
        </pre>
      </div>
    </section>
  );
}
