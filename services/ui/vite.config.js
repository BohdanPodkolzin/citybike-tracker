import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";


const historyUrl = process.env.HISTORY_URL || "http://127.0.0.1:8002";
const proxy = {
  "/api": {
    target: historyUrl,
    changeOrigin: true,
    // History is down: answer with the JSON error the UI already understands.
    configure: (p) =>
      p.on("error", (_err, _req, res) => {
        if (typeof res.writeHead !== "function") return; // a websocket, not a normal request
        if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "history service unreachable" }));
      }),
  },
};

export default defineConfig({
  plugins: [react()],
  
  server: { host: true, port: 5173, proxy },
  preview: { host: true, port: 4173, proxy },
});