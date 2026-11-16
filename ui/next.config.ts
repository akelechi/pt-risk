import type { NextConfig } from "next";

// The dev server refuses its own dev resources to origins it does not know, which leaves
// the page un-hydrated (scrubber dead) when opened as 127.0.0.1 instead of localhost.
const nextConfig: NextConfig = { allowedDevOrigins: ["127.0.0.1"] };

export default nextConfig;
