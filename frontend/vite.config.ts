import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: `npm run dev` proxies /api to the backend on :8000, so the refresh
// cookie stays same-origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
