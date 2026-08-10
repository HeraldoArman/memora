"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";

type Status = "disconnected" | "connecting" | "connected" | "error";

// ponytail: one hardcoded room — this is a local dummy-device harness.
// Add a room/identity chooser when the dashboard grows.
const DEVICE_TOPIC = "device";
const DISPLAY_TOPIC = "display";

export default function HomePage() {
  const [status, setStatus] = useState<Status>("disconnected");
  const [logs, setLogs] = useState<string[]>([]);
  const [display, setDisplay] = useState<string>("");
  const [battery, setBattery] = useState(85);
  const [buttonPressed, setButtonPressed] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const batteryRef = useRef(battery);
  const buttonRef = useRef(buttonPressed);
  batteryRef.current = battery;
  buttonRef.current = buttonPressed;

  const log = useCallback((line: string) => {
    setLogs((prev) => [...prev.slice(-80), `${new Date().toLocaleTimeString()}  ${line}`]);
  }, []);

  const publishTelemetry = useCallback(
    async (room: Room) => {
      const payload = JSON.stringify({
        battery_level: batteryRef.current,
        wifi_connected: true,
        button_pressed: buttonRef.current,
      });
      await room.localParticipant.publishData(new TextEncoder().encode(payload), {
        topic: DEVICE_TOPIC,
        reliable: true,
      });
      log(`sent telemetry: ${payload}`);
    },
    [log],
  );

  const connect = useCallback(async () => {
    if (roomRef.current) return;
    setStatus("connecting");
    log("requesting token…");
    try {
      const res = await fetch("/api/token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error ?? `token route ${res.status}`);
      }
      const { server_url, token, room_name, identity } = await res.json();
      log(`token minted — room=${room_name} identity=${identity}`);

      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;

      room.on(
        RoomEvent.DataReceived,
        (payload: Uint8Array, _participant: unknown, _kind: unknown, topic?: string) => {
          if (topic === DISPLAY_TOPIC) {
            const text = new TextDecoder().decode(payload);
            setDisplay(text);
            log(`display ← "${text.slice(0, 80)}"`);
          }
        },
      );
      room.on(RoomEvent.Disconnected, () => {
        log("disconnected");
        setStatus("disconnected");
        roomRef.current = null;
      });

      await room.connect(server_url, token);
      log(`connected to room ${room.name}`);
      await room.localParticipant.enableCameraAndMicrophone();
      log("camera + mic published");

      // attach local camera preview
      const pub = room.localParticipant.getTrackPublication(Track.Source.Camera);
      if (pub && pub.track && videoRef.current) {
        pub.track.attach(videoRef.current);
      }

      setStatus("connected");
      await publishTelemetry(room);
    } catch (err) {
      log(`error: ${err instanceof Error ? err.message : String(err)}`);
      setStatus("error");
      roomRef.current?.disconnect();
      roomRef.current = null;
    }
  }, [log, publishTelemetry]);

  const disconnect = useCallback(async () => {
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("disconnected");
  }, []);

  // re-publish telemetry when battery slider or button toggles
  useEffect(() => {
    if (status === "connected" && roomRef.current) {
      void publishTelemetry(roomRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [battery, buttonPressed]);

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
      roomRef.current = null;
    };
  }, []);

  const statusColor =
    status === "connected"
      ? "bg-emerald-500"
      : status === "connecting"
        ? "bg-amber-400"
        : status === "error"
          ? "bg-red-500"
          : "bg-neutral-500";

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Memora — Dummy Device</h1>
          <p className="text-sm text-neutral-400">
            Impersonates the ESP32-S3 glasses over LiveKit.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${statusColor}`} />
          <span className="text-neutral-300">{status}</span>
        </div>
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Camera preview + controls */}
        <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-medium text-neutral-300">Camera preview</h2>
          <video
            ref={videoRef}
            className="aspect-video w-full rounded-lg bg-black"
            autoPlay
            muted
            playsInline
          />
          <div className="mt-3 flex gap-2">
            <button
              onClick={connect}
              disabled={status === "connected" || status === "connecting"}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40"
            >
              Connect
            </button>
            <button
              onClick={disconnect}
              disabled={status !== "connected"}
              className="rounded-lg bg-neutral-700 px-4 py-2 text-sm font-medium hover:bg-neutral-600 disabled:opacity-40"
            >
              Disconnect
            </button>
          </div>
        </section>

        {/* Display (agent replies) */}
        <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-medium text-neutral-300">Agent display (OLED)</h2>
          <div className="min-h-32 rounded-lg border border-neutral-800 bg-black p-3">
            <pre className="whitespace-pre-wrap break-words font-mono text-sm text-emerald-300">
              {display || "—"}
            </pre>
          </div>
        </section>
      </div>

      {/* Telemetry controls */}
      <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-3 text-sm font-medium text-neutral-300">
          Device telemetry → topic “device”
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

      {/* Connection log */}
      <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-medium text-neutral-300">Log</h2>
        <pre className="h-48 overflow-auto rounded-lg bg-black p-3 font-mono text-xs text-neutral-400">
          {logs.join("\n")}
        </pre>
      </section>
    </main>
  );
}
