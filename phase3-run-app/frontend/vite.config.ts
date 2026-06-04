import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server runs on :8080 (matches the OAuth client's JS origins + bucket CORS).
// /api/* is proxied to the deployed Cloud Run backend so local UI work hits the
// real API (your signed-in Bearer token is forwarded). Override the target with
// VITE_API_TARGET if needed.
const API_TARGET =
  process.env.VITE_API_TARGET ||
  "https://of-batch-app-380489820300.us-central1.run.app";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 8080,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true, secure: true },
    },
  },
});
