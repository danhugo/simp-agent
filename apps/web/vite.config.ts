import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const server = process.env.SIMP_SERVER ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  test: { exclude: ["e2e/**", "node_modules/**"] },
  server: { host: "127.0.0.1", proxy: { "/api": { target: server, changeOrigin: false } } },
});
