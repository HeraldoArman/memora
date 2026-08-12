export function TelemetryControls({
  battery,
  setBattery,
  buttonPressed,
  setButtonPressed,
}: {
  battery: number;
  setBattery: (v: number) => void;
  buttonPressed: boolean;
  setButtonPressed: (v: boolean) => void;
}) {
  return (
    <section className="rounded-xl border border-ink-700 bg-ink-850 p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-medium text-neutral-700">
        Device telemetry &rarr; topic &ldquo;device&rdquo;
      </h2>
      <div className="flex flex-wrap items-center gap-6">
        <label className="flex items-center gap-3 text-sm text-neutral-800">
          <input
            type="checkbox"
            checked={buttonPressed}
            onChange={(e) => setButtonPressed(e.target.checked)}
            className="h-4 w-4 accent-accent-500"
          />
          <span>button_pressed</span>
        </label>
        <label className="flex items-center gap-3 text-sm text-neutral-800">
          battery_level
          <input
            type="range"
            min={0}
            max={100}
            value={battery}
            onChange={(e) => setBattery(Number(e.target.value))}
            className="w-40 accent-accent-500"
          />
          <span className="w-8 tabular-nums">{battery}%</span>
        </label>
      </div>
    </section>
  );
}
