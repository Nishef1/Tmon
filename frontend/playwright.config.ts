import { defineConfig, devices } from "@playwright/test";

const WEB = 3100;
const API = 8787;
// Locally, PW_CHANNEL=chrome reuses the installed Chrome instead of downloading a Playwright browser.
const channel = process.env.PW_CHANNEL || undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${WEB}`, trace: "retain-on-failure" },
  projects: [
    { name: "mobile", use: { ...devices["Pixel 7"], channel } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel } },
  ],
  webServer: [
    {
      // Fixture API: canned responses only, never real market data (see e2e/mock-api.mjs).
      command: "node e2e/mock-api.mjs",
      port: API,
      env: { PORT: String(API) },
      reuseExistingServer: !process.env.CI,
    },
    {
      // A production build: what ships, and no dev-server origin restrictions.
      command: `pnpm exec next build && pnpm exec next start --port ${WEB}`,
      port: WEB,
      env: {
        API_URL: `http://127.0.0.1:${API}`,
        // read by the browser-side live panel; inlined at build time
        NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API}`,
      },
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
    },
  ],
});
