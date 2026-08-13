"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Room,
  RoomEvent,
  Track,
  VideoQuality,
  type RemoteTrack,
  type RemoteTrackPublication,
} from "livekit-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";

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
  const [logs, setLogs] = useState<string[]>([]);

  const roomRef = useRef<Room | null>(null);

  const log = useCallback((line: string) => {
    setLogs((prev) => [...prev.slice(-80), `${new Date().toLocaleTimeString()}  ${line}`]);
  }, []);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameCountRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const stopFrameProbe = useCallback(() => {
    if (rafRef.current !== null) {
      // rafRef holds either a setInterval ID (number) or a requestVideoFrameCallback
      // handle (number). Both are cancelled by the same APIs.
      const video = videoRef.current;
      if (video && "cancelVideoFrameCallback" in video) {
        video.cancelVideoFrameCallback(rafRef.current);
      } else {
        clearInterval(rafRef.current);
      }
      rafRef.current = null;
    }
  }, []);

  const startFrameProbe = useCallback(() => {
    stopFrameProbe();
    const video = videoRef.current;
    if (!video) return;

    // ponytail: use requestVideoFrameCallback when available — it fires on
    // actual decoded frames, not a fixed timer. Falls back to setInterval for
    // browsers without it (Safari < 14). The 1s interval was missing frames
    // on deployment because readyState check can fall between frame intervals.
    const hasRVFC = "requestVideoFrameCallback" in HTMLVideoElement.prototype;
    if (hasRVFC) {
      const onFrame = () => {
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
          frameCountRef.current += 1;
          setFrameCount(frameCountRef.current);
          setLastFrame(new Date().toLocaleTimeString());
          setDimensions(`${video.videoWidth || "—"} × ${video.videoHeight || "—"}`);
        }
        rafRef.current = video.requestVideoFrameCallback(onFrame);
      };
      rafRef.current = video.requestVideoFrameCallback(onFrame);
    } else {
      rafRef.current = window.setInterval(() => {
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
          frameCountRef.current += 1;
          setFrameCount(frameCountRef.current);
          setLastFrame(new Date().toLocaleTimeString());
          setDimensions(`${video.videoWidth || "—"} × ${video.videoHeight || "—"}`);
        }
      }, 1000);
    }
  }, [stopFrameProbe]);

  const attachRemoteVideo = useCallback(
    (track: RemoteTrack, publication?: RemoteTrackPublication) => {
      if (!videoRef.current) return;
      // ponytail: pin max quality + FPS so the SFU doesn't throttle this subscriber
      // on slow links. The ESP32 publishes a single-layer H.264 stream at 1 FPS;
      // without this, LiveKit's congestion control drops frames to 1/5–1/10 FPS.
      if (publication) {
        publication.setVideoQuality(VideoQuality.HIGH);
        publication.setVideoFPS(1);
      }
      track.attach(videoRef.current);
      setTrackState("H.264 track attached");
      setMessage("Receiving encoded video from LiveKit");
      log(`track attached: ${track.sid} (${track.source})`);
      startFrameProbe();
    },
    [log, startFrameProbe],
  );

  const disconnect = useCallback(async () => {
    log("stopping receiver");
    stopFrameProbe();
    videoRef.current?.pause();
    videoRef.current?.removeAttribute("src");
    videoRef.current?.load();
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("idle");
    setTrackState("waiting for remote video");
    setMessage("No receiver attached");
    log("disconnected");
  }, [log, stopFrameProbe]);

  const connect = useCallback(async () => {
    if (roomRef.current || !roomName.trim()) return;
    setStatus("connecting");
    setMessage("Requesting subscriber token…");
    setTrackState("joining room");
    setFrameCount(0);
    frameCountRef.current = 0;
    log(`joining room "${roomName.trim()}"`);

    try {
      const response = await fetch("/api/token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ room_name: roomName.trim(), identity: MONITOR_IDENTITY }),
      });
      if (!response.ok) throw new Error(`token route ${response.status}`);
      log(`token route ${response.status}`);

      const { server_url: serverUrl, token } = await response.json();
      const room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track, publication) => {
        if (track.kind === Track.Kind.Video) {
          log(`subscribed: ${track.sid} video`);
          attachRemoteVideo(track as RemoteTrack, publication as RemoteTrackPublication);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        if (track.kind === Track.Kind.Video) {
          log(`unsubscribed: ${track.sid} video`);
          if (videoRef.current) track.detach(videoRef.current);
          stopFrameProbe();
          setTrackState("remote video detached");
        }
      });
      room.on(RoomEvent.Disconnected, () => {
        log("room disconnected");
        roomRef.current = null;
        setStatus("idle");
        setTrackState("waiting for remote video");
        setMessage("Receiver disconnected");
      });

      await room.connect(serverUrl, token, { autoSubscribe: true });
      setStatus("connected");
      setMessage(`Listening to ${room.name}`);
      setTrackState("connected; waiting for video track");
      log(`connected to room "${room.name}"`);
      log(
        `remote participants: ${Array.from(room.remoteParticipants.keys()).join(", ") || "none"}`,
      );

      for (const publication of room.remoteParticipants.values()) {
        for (const remotePublication of publication.trackPublications.values()) {
          if (remotePublication.track && remotePublication.kind === Track.Kind.Video) {
            attachRemoteVideo(
              remotePublication.track as RemoteTrack,
              remotePublication as RemoteTrackPublication,
            );
          }
        }
      }
    } catch (error) {
      log(`error: ${error instanceof Error ? error.message : String(error)}`);
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Unable to connect");
      roomRef.current = null;
    }
  }, [attachRemoteVideo, log, roomName, stopFrameProbe]);

  useEffect(() => {
    return () => {
      stopFrameProbe();
      void roomRef.current?.disconnect();
    };
  }, [stopFrameProbe]);

  const connected = status === "connected";

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link
            href="/debugging"
            className="font-mono text-xs uppercase tracking-widest text-ink-500 hover:text-accent-500"
          >
            ← back to device lab
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-neutral-900">H.264 Signal Scope</h1>
          <p className="mt-1 text-sm text-neutral-600">
            A dedicated receiver for the physical ESP32 track. This page never enables the browser
            camera or microphone; it only subscribes to LiveKit.
          </p>
        </div>
        <Badge
          variant={connected ? "ok" : status === "error" ? "crit" : "default"}
          className="self-start sm:self-auto"
        >
          {statusLabel(status)}
        </Badge>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(290px,.7fr)]">
        <Card>
          <CardHeader
            title="Remote Video"
            subtitle={`LiveKit decode surface · ${connected ? "live" : "offline"}`}
          />
          <CardBody>
            <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden rounded-lg bg-ink-900 ring-1 ring-inset ring-ink-700">
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                className="h-full w-full object-contain"
              />
              {!connected || frameCount === 0 ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-lg bg-ink-900/85 text-center">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-ink-600 border-t-accent-500" />
                  <p className="font-mono text-xs uppercase tracking-widest text-ink-500">
                    {trackState}
                  </p>
                </div>
              ) : null}
              <div className="absolute left-4 top-4 flex items-center gap-2 rounded bg-ink-900/80 px-2 py-1 font-mono text-xs uppercase tracking-widest text-accent-500">
                <span className="h-1.5 w-1.5 rounded-full bg-accent-500" /> decoded
              </div>
              <span className="absolute bottom-3 right-3 rounded bg-ink-900/80 px-2 py-1 font-mono text-xs text-ink-500">
                {dimensions}
              </span>
            </div>
            <p className="mt-3 font-mono text-xs text-ink-500">{message}</p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Receiver Controls"
            subtitle={`subscriber identity: ${MONITOR_IDENTITY}`}
          />
          <CardBody className="flex flex-col gap-6">
            <div>
              <label
                htmlFor="room-name"
                className="block font-mono text-xs uppercase tracking-widest text-ink-500"
              >
                LiveKit room
              </label>
              <input
                id="room-name"
                value={roomName}
                onChange={(event) => setRoomName(event.target.value)}
                disabled={status === "connecting" || connected}
                className="mt-2 w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-sm text-neutral-900 outline-none transition focus:border-accent-500 disabled:opacity-50"
              />
            </div>

            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-ink-700 bg-ink-700">
              <div className="bg-ink-800 p-4">
                <p className="font-mono text-xs uppercase tracking-widest text-ink-500">
                  frames seen
                </p>
                <p className="mt-1 text-2xl font-semibold text-accent-500">{frameCount}</p>
              </div>
              <div className="bg-ink-800 p-4">
                <p className="font-mono text-xs uppercase tracking-widest text-ink-500">
                  last frame
                </p>
                <p className="mt-1 truncate font-mono text-sm text-neutral-700">{lastFrame}</p>
              </div>
            </div>

            <div className="space-y-4 border-l border-ink-700 pl-4 font-mono text-sm">
              <div>
                <span className="text-ink-500">01 / signaling</span>
                <p className="mt-1 text-neutral-700">
                  {status === "idle" ? "not started" : "LiveKit connected"}
                </p>
              </div>
              <div>
                <span className="text-ink-500">02 / subscription</span>
                <p className="mt-1 text-neutral-700">{trackState}</p>
              </div>
              <div>
                <span className="text-ink-500">03 / browser decode</span>
                <p className="mt-1 text-neutral-700">
                  {frameCount > 0 ? "frames advancing" : "awaiting frames"}
                </p>
              </div>
            </div>

            <div className="mt-auto flex gap-2 pt-2">
              <Button
                variant="primary"
                onClick={() => void connect()}
                disabled={connected || status === "connecting" || !roomName.trim()}
                className="flex-1"
              >
                {status === "connecting" ? "Joining…" : "Attach receiver"}
              </Button>
              <Button onClick={() => void disconnect()} disabled={!connected && status !== "error"}>
                Stop
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Receiver Log" subtitle={`${logs.length} line(s)`} />
        <CardBody>
          <pre className="h-52 overflow-auto font-mono text-xs leading-5 text-ink-500">
            {logs.length ? logs.join("\n") : "no events logged yet"}
          </pre>
        </CardBody>
      </Card>
    </div>
  );
}
