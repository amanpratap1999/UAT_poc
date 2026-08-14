import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBaseUrl = (env.VITE_API_BASE_URL || process.env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      host: true, // Listen on all addresses for container / Codespaces port forwarding
      ...(apiBaseUrl
        ? {
            proxy: {
              "/api": {
                target: apiBaseUrl,
                changeOrigin: true,
                secure: false,
              },
            },
          }
        : {}),
    },
  };
});
