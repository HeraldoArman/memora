import type { NextConfig } from "next";

// ponytail: standalone output → minimal Docker image (.next/standalone + static),
// no node_modules in the runner. Railway serves `next start` (or the standalone server).
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
