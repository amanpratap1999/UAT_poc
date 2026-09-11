import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
export function resolveProxyTarget(env) {
    const apiBaseUrl = (env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");
    if (apiBaseUrl) {
        return apiBaseUrl;
    }
    const devProxyTarget = (env.VITE_DEV_API_PROXY_TARGET || "http://127.0.0.1:8000")
        .trim()
        .replace(/\/+$/, "");
    return devProxyTarget || "http://127.0.0.1:8000";
}
export function getViteServerConfig(env) {
    const target = resolveProxyTarget(env);
    return {
        port: 5173,
        host: true, // Listen on all addresses for container / Codespaces port forwarding
        proxy: {
            "/api": {
                target,
                changeOrigin: true,
                secure: false,
            },
        },
    };
}
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), "");
    const mergedEnv = { ...env, ...process.env };
    return {
        plugins: [react()],
        resolve: {
            alias: {
                "@": path.resolve(__dirname, "./src"),
            },
        },
        server: getViteServerConfig(mergedEnv),
    };
});
