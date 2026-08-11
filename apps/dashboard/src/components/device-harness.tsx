"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import { AgentDisplay } from "@/components/device/agent-display";
import { CameraPreview } from "@/components/device/camera-preview";
import { ConnectionLog } from "@/components/device/connection-log";
import { StatusBadge, type Status } from "@/components/device/status-badge";
import { TelemetryControls } from "@/components/device/telemetry-controls";

// ponytail: one hardcoded room — this is a local dummy-device harness.
// Add a room/identity chooser when the dashboard grows.
const DEVICE_TOPIC = "device";
const DISPLAY_TOPIC = "display";

export function DeviceHarness() {
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

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Memora — Dummy Device</h1>
          <p className="text-sm text-neutral-400">
            Impersonates the ESP32-S3 glasses over LiveKit.
          </p>
        </div>
        <StatusBadge status={status} />
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-3">
          <CameraPreview videoRef={videoRef} />
          <div className="flex gap-2">
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
        <AgentDisplay text={display} />
      </div>

      <TelemetryControls
        battery={battery}
        setBattery={setBattery}
        buttonPressed={buttonPressed}
        setButtonPressed={setButtonPressed}
      />

      <ConnectionLog logs={logs} />
    </main>
  );
}
