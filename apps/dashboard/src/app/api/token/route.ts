import { AccessToken, LiveKitAPI } from "livekit-server-sdk";
import { NextResponse } from "next/server";
import { getServerEnv } from "@/lib/env";

// ponytail: no auth — this is a local dummy-device test harness. Each Connect
// gets a fresh unique room so the LiveKit dev-mode worker always sees a clean
// participant-join event (a stale participant in a reused room never re-triggers
// an agent dispatch). Add auth before exposing the dashboard publicly.

const DEFAULT_IDENTITY = "dummy-device";

function uniqueRoom(): string {
  // memora-<timestamp>-<rand> — unique enough for local dev; collides are harmless
  // (LiveKit merges same-room joins, but the timestamp makes that near-impossible).
  return `memora-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export async function POST(request: Request) {
  let serverUrl: string;
  let apiKey: string;
  let apiSecret: string;
  let agentName: string;
  try {
    const env = getServerEnv();
    serverUrl = env.LIVEKIT_URL;
    apiKey = env.LIVEKIT_API_KEY;
    apiSecret = env.LIVEKIT_API_SECRET;
    agentName = env.AGENT_NAME;
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "env invalid" },
      { status: 500 },
    );
  }

  let roomName = uniqueRoom();
  let identity = DEFAULT_IDENTITY;
  try {
    const body = await request.json();
    if (typeof body.room_name === "string" && body.room_name.trim())
      roomName = body.room_name.trim();
    if (typeof body.identity === "string" && body.identity.trim()) identity = body.identity.trim();
  } catch {
    // no body or invalid JSON → fresh unique room
  }

  const at = new AccessToken(apiKey, apiSecret, { identity, ttl: "2h" });
  const isMonitor = identity === "h264-monitor";
  at.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: !isMonitor,
    // The physical ESP32 has a microphone but no speaker. Prevent its
    // LiveKit client from subscribing to the agent's audio track; the
    // current ESP32 SDK still allocates a subscriber/renderer for it even
    // when the application leaves room_options.subscribe empty.
    canSubscribe: identity !== "memora-device",
    canPublishData: !isMonitor,
  });

  const token = await at.toJwt();

  // Explicitly dispatch the agent to the room — RoomAgentDispatch in the token's
  // roomConfig only works with LiveKit Cloud dispatch rules pre-configured. Calling
  // LiveKitAPI.agentDispatch.createDispatch directly is reliable for both Cloud and self-hosted.
  const httpUrl = serverUrl.replace("wss://", "https://").replace("ws://", "http://");
  const api = new LiveKitAPI({ host: httpUrl, apiKey, secret: apiSecret });
  try {
    const dispatch = await api.agentDispatch.createDispatch(roomName, agentName);
    console.log("[token] agent dispatch created:", dispatch.id, "room:", roomName);
  } catch (err) {
    console.error("[token] agent dispatch failed:", err instanceof Error ? err.message : err);
  }

  return NextResponse.json({ server_url: serverUrl, token, room_name: roomName, identity });
}
