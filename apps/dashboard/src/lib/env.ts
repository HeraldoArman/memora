import { z } from "zod";

// ponytail: single source of truth for dashboard env — validated once at import,
// fails loudly (like the backend's get_settings()). No silent undefineds.

const schema = z.object({
  // server-side — used by /api/token to mint tokens. Never prefixed NEXT_PUBLIC_.
  LIVEKIT_URL: z
    .string()
    .url("LIVEKIT_URL must be a valid ws/wss URL")
    .refine((v) => v.startsWith("ws"), "LIVEKIT_URL must start with ws:// or wss://"),
  LIVEKIT_API_KEY: z.string().min(1, "LIVEKIT_API_KEY is required"),
  LIVEKIT_API_SECRET: z.string().min(1, "LIVEKIT_API_SECRET is required"),
  AGENT_NAME: z.string().min(1, "AGENT_NAME is required"),
  // public — exposed to the browser so the client knows the server address.
  NEXT_PUBLIC_LIVEKIT_URL: z
    .string()
    .url("NEXT_PUBLIC_LIVEKIT_URL must be a valid ws/wss URL")
    .refine((v) => v.startsWith("ws"), "NEXT_PUBLIC_LIVEKIT_URL must start with ws:// or wss://"),
});

export type Env = z.infer<typeof schema>;

let cached: Env | null = null;

/**
 * Server env (LIVEKIT_* keys). Cached after first validation. Throws with a
 * readable message listing every missing/invalid key — never a silent undefined.
 */
export function getServerEnv(): Env {
  if (cached) return cached;
  const parsed = schema.safeParse({
    LIVEKIT_URL: process.env.LIVEKIT_URL,
    LIVEKIT_API_KEY: process.env.LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET: process.env.LIVEKIT_API_SECRET,
    AGENT_NAME: process.env.AGENT_NAME,
    NEXT_PUBLIC_LIVEKIT_URL: process.env.NEXT_PUBLIC_LIVEKIT_URL,
  });
  if (!parsed.success) {
    const msg = parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new Error(`Dashboard env invalid — ${msg}`);
  }
  cached = parsed.data;
  return cached;
}

/**
 * Public env (NEXT_PUBLIC_* only). Safe to read in the browser. Use this in
 * client components instead of reading process.env directly — it validates.
 */
export function getPublicEnv(): { livekitUrl: string; workerHealthUrl: string } {
  const livekitUrl = process.env.NEXT_PUBLIC_LIVEKIT_URL;
  const workerHealthUrl = process.env.NEXT_PUBLIC_WORKER_HEALTH_URL;
  const parsed = z
    .object({
      livekitUrl: z
        .string()
        .url()
        .refine((v) => v.startsWith("ws")),
      workerHealthUrl: z
        .string()
        .url()
        .refine((v) => v.startsWith("http")),
    })
    .safeParse({ livekitUrl, workerHealthUrl });
  if (!parsed.success) {
    throw new Error("NEXT_PUBLIC_LIVEKIT_URL or NEXT_PUBLIC_WORKER_HEALTH_URL missing/invalid");
  }
  return parsed.data;
}
