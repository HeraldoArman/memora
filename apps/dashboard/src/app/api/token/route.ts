import { AccessToken } from "livekit-server-sdk";
import { NextResponse } from "next/server";
import { getServerEnv } from "@/lib/env";

// ponytail: no auth, hardcoded room — this is a local dummy-device test harness.
// Add auth + a room/identity chooser before exposing the dashboard publicly.

const DEFAULT_ROOM = "memora-test";
const DEFAULT_IDENTITY = "dummy-device";

export async function POST(request: Request) {
  let serverUrl: string;
  let apiKey: string;
  let apiSecret: string;
  try {
    const env = getServerEnv();
    serverUrl = env.LIVEKIT_URL;
    apiKey = env.LIVEKIT_API_KEY;
    apiSecret = env.LIVEKIT_API_SECRET;
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "env invalid" },
      { status: 500 },
    );
  }

  let roomName = DEFAULT_ROOM;
  let identity = DEFAULT_IDENTITY;
  try {
    const body = await request.json();
    if (typeof body.room_name === "string" && body.room_name.trim())
      roomName = body.room_name.trim();
    if (typeof body.identity === "string" && body.identity.trim()) identity = body.identity.trim();
  } catch {
    // no body or invalid JSON → use defaults
  }

  const at = new AccessToken(apiKey, apiSecret, { identity, ttl: "2h" });
  at.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });

  const token = await at.toJwt();
  return NextResponse.json({ server_url: serverUrl, token, room_name: roomName, identity });
}
