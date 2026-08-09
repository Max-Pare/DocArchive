/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // dev convenience: forward API calls to the backend
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    // no auto-injected describe/it/expect: every test imports them explicitly
    globals: false,
    setupFiles: "./src/test/setup.ts",
    // components import styles.css only via main.tsx; skip CSS processing entirely
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/vite-env.d.ts", "src/test/**", "**/*.test.*"],
      // No thresholds yet. @vitest/coverage-v8 has been installed and unused
      // since it landed, so the first job of this config is simply to make the
      // number visible; a ratchet gets set from that measurement later.
    },
  },
});
