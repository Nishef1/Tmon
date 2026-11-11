import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  // e2e builds (with a fixture API url baked in) must not overwrite the normal build
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
};

export default config;
