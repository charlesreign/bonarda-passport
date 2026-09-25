import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: `npm run dev` proxies /api to the backend on :8000, so the refresh
// cookie stays same-origin.
export default defineConfig({
  plugins: [react()],
  // The manifest lets scripts/check-size.mjs follow each route's chunk graph.
  build: { manifest: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
