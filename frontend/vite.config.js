import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5273,
    proxy: { "/api": "http://localhost:8731" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
