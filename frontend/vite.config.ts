import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to the backend on :8000. In production set VITE_API_URL at build time.
export default defineConfig({ plugins: [react()], server: { proxy: { "/api": "http://localhost:8000" } } });
