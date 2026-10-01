import { defineConfig } from "vitest/config";

export default defineConfig({
  // Relative asset paths, so the built site works from any sub-path
  // (GitHub Pages serves it under /One-Million-Years-Trade-Depot/).
  base: "./",
  build: {
    outDir: "dist",
    target: "es2022",
    // The core carries ~570 KB of name tables (about 210 KB gzipped).
    chunkSizeWarningLimit: 800,
  },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
