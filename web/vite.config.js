import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // 部署到子路径时改这里，例如 base: "/pdf/"
  base: "./",
  server: { port: 5274 },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
});
