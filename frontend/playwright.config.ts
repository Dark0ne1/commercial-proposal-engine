import { defineConfig } from "@playwright/test";
export default defineConfig({testDir: "tests", timeout: 120000, use: {actionTimeout:15000, timezoneId: "Europe/Moscow", baseURL: process.env.E2E_URL || "http://127.0.0.1:3000", browserName: "chromium", launchOptions: {channel: "chrome"}}, workers: 1});
