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
    <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-300">
        Device telemetry &rarr; topic &ldquo;device&rdquo;
      </h2>
      <div className="flex flex-wrap items-center gap-6">
        <label className="flex items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={buttonPressed}
            onChange={(e) => setButtonPressed(e.target.checked)}
            className="h-4 w-4"
          />
          <span>button_pressed</span>
        </label>
        <label className="flex items-center gap-3 text-sm">
          battery_level
          <input
            type="range"
            min={0}
            max={100}
            value={battery}
            onChange={(e) => setBattery(Number(e.target.value))}
            className="w-40"
          />
          <span className="w-8 tabular-nums">{battery}%</span>
        </label>
      </div>
    </section>
  );
}
