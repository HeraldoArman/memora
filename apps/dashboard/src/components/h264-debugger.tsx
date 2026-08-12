"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";

type ConnectionStatus = "idle" | "connecting" | "connected" | "error";

const DEFAULT_ROOM = "memora-test";
const MONITOR_IDENTITY = "h264-monitor";

function statusLabel(status: ConnectionStatus): string {
  switch (status) {
    case "connecting":
      return "CONNECTING";
    case "connected":
      return "LISTENING";
    case "error":
      return "FAULT";
    default:
      return "STANDBY";
  }
}

export function H264Debugger() {
  const [roomName, setRoomName] = useState(DEFAULT_ROOM);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [message, setMessage] = useState("No receiver attached");
  const [trackState, setTrackState] = useState("waiting for remote video");
  const [frameCount, setFrameCount] = useState(0);
  const [dimensions, setDimensions] = useState("—");
  const [lastFrame, setLastFrame] = useState("—");

  const roomRef = useRef<Room | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameCountRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const stopFrameProbe = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const startFrameProbe = useCallback(() => {
    stopFrameProbe();
    const video = videoRef.current;
    if (!video) return;

    const probe = () => {
      if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        frameCountRef.current += 1;
        setFrameCount(frameCountRef.current);
        setLastFrame(new Date().toLocaleTimeString());
        setDimensions(`${video.videoWidth || "—"} × ${video.videoHeight || "—"}`);
      }
      rafRef.current = requestAnimationFrame(probe);
    };
    rafRef.current = requestAnimationFrame(probe);
  }, [stopFrameProbe]);

  const attachRemoteVideo = useCallback(
    (track: RemoteTrack) => {
      if (!videoRef.current) return;
      track.attach(videoRef.current);
      setTrackState("H.264 track attached");
      setMessage("Receiving encoded video from LiveKit");
      startFrameProbe();
    },
    [startFrameProbe],
  );

  const disconnect = useCallback(async () => {
    stopFrameProbe();
    videoRef.current?.pause();
    videoRef.current?.removeAttribute("src");
    videoRef.current?.load();
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("idle");
    setTrackState("waiting for remote video");
    setMessage("No receiver attached");
  }, [stopFrameProbe]);

  const connect = useCallback(async () => {
    if (roomRef.current || !roomName.trim()) return;
    setStatus("connecting");
    setMessage("Requesting subscriber token…");
    setTrackState("joining room");
    setFrameCount(0);
    frameCountRef.current = 0;

    try {
      const response = await fetch("/api/token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ room_name: roomName.trim(), identity: MONITOR_IDENTITY }),
      });
      if (!response.ok) throw new Error(`token route ${response.status}`);

      const { server_url: serverUrl, token } = await response.json();
      const room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track, _publication, _participant) => {
        if (track.kind === Track.Kind.Video) {
          attachRemoteVideo(track as RemoteTrack);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        if (track.kind === Track.Kind.Video) {
          if (videoRef.current) track.detach(videoRef.current);
          stopFrameProbe();
          setTrackState("remote video detached");
        }
      });
      room.on(RoomEvent.Disconnected, () => {
        roomRef.current = null;
        setStatus("idle");
        setTrackState("waiting for remote video");
        setMessage("Receiver disconnected");
      });

      await room.connect(serverUrl, token, { autoSubscribe: true });
      setStatus("connected");
      setMessage(`Listening to ${room.name}`);
      setTrackState("connected; waiting for video track");

      for (const publication of room.remoteParticipants.values()) {
        for (const remotePublication of publication.trackPublications.values()) {
          if (remotePublication.track && remotePublication.kind === Track.Kind.Video) {
            attachRemoteVideo(remotePublication.track as RemoteTrack);
          }
        }
      }
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Unable to connect");
      roomRef.current = null;
    }
  }, [attachRemoteVideo, roomName, stopFrameProbe]);

  useEffect(() => {
    return () => {
      stopFrameProbe();
      void roomRef.current?.disconnect();
    };
  }, [stopFrameProbe]);

  const connected = status === "connected";

  return (
    <main className="min-h-screen overflow-hidden bg-[#090a09] text-[#f4f1e7]">
      <div className="pointer-events-none fixed inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.035)_1px,transparent_1px)] [background-size:42px_42px]" />
      <div className="relative mx-auto max-w-7xl px-5 py-6 sm:px-8 sm:py-10">
        <header className="mb-10 flex flex-col gap-6 border-b border-[#343731] pb-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Link href="/debugging" className="font-mono text-[11px] uppercase tracking-[0.24em] text-[#a4ad91] hover:text-[#d8e7b6]">
              ← back to device lab
            </Link>
            <p className="mt-7 font-mono text-xs uppercase tracking-[0.32em] text-[#d8e7b6]">Memora / media lab 04</p>
            <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-[-0.045em] text-[#f4f1e7] sm:text-6xl">
              H.264 signal scope
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[#a7aaa0]">
              A dedicated receiver for the physical ESP32 track. This page never enables the browser camera or microphone; it only subscribes to LiveKit.
            </p>
          </div>
          <div className="flex items-center gap-3 self-start sm:self-auto">
            <span className={`h-2 w-2 rounded-full ${status === "connected" ? "bg-[#c8f36a] shadow-[0_0_14px_#c8f36a]" : status === "error" ? "bg-[#ff735c]" : "bg-[#777d6f]"}`} />
            <span className="font-mono text-xs tracking-[0.2em] text-[#d6d8cb]">{statusLabel(status)}</span>
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(290px,.7fr)]">
          <div className="border border-[#454b3e] bg-[#111410] p-3 shadow-[0_22px_80px_rgba(0,0,0,.35)] sm:p-5">
            <div className="mb-4 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.22em] text-[#87917a]">
              <span>remote video / decode surface</span>
              <span className="text-[#c8f36a]">{connected ? "live" : "offline"}</span>
            </div>
            <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden bg-[#050605] ring-1 ring-inset ring-[#2f362d]">
              <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-contain" />
              {!connected || frameCount === 0 ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#050605]/85 text-center">
                  <div className="h-10 w-10 rounded-full border border-[#536149] border-t-[#c8f36a] animate-spin" />
                  <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#a7aaa0]">{trackState}</p>
                </div>
              ) : null}
              <div className="absolute left-4 top-4 flex items-center gap-2 bg-[#090a09]/80 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-[#c8f36a]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#c8f36a]" /> decoded
              </div>
              <span className="absolute bottom-3 right-3 bg-[#090a09]/80 px-2 py-1 font-mono text-[10px] text-[#a7aaa0]">{dimensions}</span>
            </div>
            <p className="mt-4 font-mono text-xs text-[#8f9688]">{message}</p>
          </div>

          <aside className="flex flex-col border border-[#343b31] bg-[#0e110e] p-5">
            <div className="mb-8">
              <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-[#87917a]">Receiver controls</p>
              <label className="mt-5 block font-mono text-[10px] uppercase tracking-[0.18em] text-[#a7aaa0]" htmlFor="room-name">LiveKit room</label>
              <input
                id="room-name"
                value={roomName}
                onChange={(event) => setRoomName(event.target.value)}
                disabled={status === "connecting" || connected}
                className="mt-2 w-full border border-[#485145] bg-[#171b16] px-3 py-3 font-mono text-sm text-[#f4f1e7] outline-none transition focus:border-[#c8f36a] disabled:opacity-50"
              />
              <p className="mt-2 font-mono text-[10px] leading-5 text-[#727a6e]">subscriber identity: {MONITOR_IDENTITY}</p>
            </div>

            <div className="mb-8 grid grid-cols-2 gap-px border border-[#343b31] bg-[#343b31]">
              <div className="bg-[#111410] p-4"><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#727a6e]">frames seen</p><p className="mt-2 text-2xl font-semibold text-[#c8f36a]">{frameCount}</p></div>
              <div className="bg-[#111410] p-4"><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#727a6e]">last frame</p><p className="mt-2 truncate font-mono text-sm text-[#f4f1e7]">{lastFrame}</p></div>
            </div>

            <div className="space-y-4 border-l border-[#46523d] pl-4 font-mono text-xs">
              <div><span className="text-[#727a6e]">01 / signaling</span><p className="mt-1 text-[#c8f36a]">{status === "idle" ? "not started" : "LiveKit connected"}</p></div>
              <div><span className="text-[#727a6e]">02 / subscription</span><p className="mt-1 text-[#c8f36a]">{trackState}</p></div>
              <div><span className="text-[#727a6e]">03 / browser decode</span><p className="mt-1 text-[#c8f36a]">{frameCount > 0 ? "frames advancing" : "awaiting frames"}</p></div>
            </div>

            <div className="mt-auto flex gap-2 pt-10">
              <button onClick={() => void connect()} disabled={connected || status === "connecting" || !roomName.trim()} className="flex-1 bg-[#c8f36a] px-4 py-3 font-mono text-xs font-bold uppercase tracking-[0.14em] text-[#11150d] transition hover:bg-[#ddff91] disabled:cursor-not-allowed disabled:opacity-35">{status === "connecting" ? "Joining…" : "Attach receiver"}</button>
              <button onClick={() => void disconnect()} disabled={!connected && status !== "error"} className="border border-[#4b5547] px-4 py-3 font-mono text-xs uppercase tracking-[0.14em] text-[#d0d5c9] transition hover:border-[#c8f36a] disabled:cursor-not-allowed disabled:opacity-35">Stop</button>
            </div>
          </aside>
        </section>

        <footer className="mt-8 flex flex-col gap-2 border-t border-[#343731] pt-5 font-mono text-[10px] uppercase tracking-[0.16em] text-[#727a6e] sm:flex-row sm:justify-between">
          <span>source: memora-device / codec: H.264 / transport: WebRTC</span>
          <span>diagnostic view · no local capture</span>
        </footer>
      </div>
    </main>
  );
}
