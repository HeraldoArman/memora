import type { NextConfig } from "next";

// ponytail: standalone output → minimal Docker image (.next/standalone + static),
// no node_modules in the runner. Railway serves `next start` (or the standalone server).
// Rewrites proxy /api/dashboard/* → backend so the browser avoids CORS entirely.
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/dashboard/:path*",
        destination: `${backendUrl}/api/dashboard/:path*`,
      },
    ];
  },
};

export default nextConfig;
