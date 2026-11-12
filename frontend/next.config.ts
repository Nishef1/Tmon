import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  // e2e builds (with a fixture API url baked in) must not overwrite the normal build
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  // `next dev` opened from a phone or another PC on the Wi-Fi: without this Next refuses the page's
  // scripts from a non-localhost origin, nothing hydrates and every button (the menu) is dead.
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "172.*.*.*", "*.local"],
};

export default config;
