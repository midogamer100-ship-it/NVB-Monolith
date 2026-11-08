import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the FastAPI backend runs on :8080; the built assets are served
// by that same backend in every deployment (VM and containers).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: false },
      "/health": { target: "http://localhost:8080", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
});
