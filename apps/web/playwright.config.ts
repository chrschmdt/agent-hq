import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "make -C ../.. api-offline PACE=0",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "pnpm dev --port 3000",
      url: "http://localhost:3000/overview",
      env: {
        AHQ_OPERATOR_TOKEN: "local-operator-token",
        API_INTERNAL_URL: "http://localhost:8000",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
