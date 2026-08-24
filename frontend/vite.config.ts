import { cloudflare } from "@cloudflare/vite-plugin";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), cloudflare()],
  server: {
    proxy: {
      "/local-api": { target: "http://127.0.0.1:8000", changeOrigin: true, rewrite: (path) => path.replace(/^\/local-api/, "") },
      "/local-ws": { target: "ws://127.0.0.1:8000", ws: true, rewrite: () => "/ws" },
    },
  },
});
