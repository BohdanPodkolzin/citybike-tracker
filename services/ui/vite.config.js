import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development Vite forwards /api to the History service, the same job nginx
// will do on the UI VM later. The browser only ever talks to ONE origin, so no
// CORS is needed and the UI code uses relative paths (/api/...) everywhere.
//   HISTORY_URL=http://192.168.0.52:8002 npm run dev   <- point it elsewhere
const historyUrl = process.env.HISTORY_URL || "http://127.0.0.1:8002";
const proxy = { "/api": { target: historyUrl, changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  // host: true = listen on every address, so a phone in your LAN can open
  // http://<your-computer-ip>:5173 while you develop.
  server: { host: true, port: 5173, proxy },
  preview: { host: true, port: 4173, proxy },
});
