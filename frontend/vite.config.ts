import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During `vite dev` (outside Docker), proxy /api to the local backend so the
// frontend runs single-origin, matching the nginx setup used in production.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
