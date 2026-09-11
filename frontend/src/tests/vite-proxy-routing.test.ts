import { describe, it, expect } from "vitest";
import { resolveProxyTarget, getViteServerConfig } from "../../vite.config";
import { getApiBaseUrl, resolveApiUrl } from "@/lib/api-client";

interface ProxyRule {
  target: string;
  changeOrigin?: boolean;
  secure?: boolean;
}

describe("Vite Local API Routing and Docker Parity", () => {
  it("proxies /api to default local target (http://127.0.0.1:8000) when VITE_API_BASE_URL is empty", () => {
    const env = {
      VITE_API_BASE_URL: "",
      VITE_DEV_API_PROXY_TARGET: "",
    };

    const target = resolveProxyTarget(env);
    expect(target).toBe("http://127.0.0.1:8000");

    const serverConfig = getViteServerConfig(env);
    const proxy = serverConfig.proxy as Record<string, ProxyRule>;
    expect(proxy).toBeDefined();
    expect(proxy["/api"].target).toBe("http://127.0.0.1:8000");
    expect(proxy["/api"].changeOrigin).toBe(true);
  });

  it("proxies /api to custom VITE_DEV_API_PROXY_TARGET when provided", () => {
    const env = {
      VITE_API_BASE_URL: "",
      VITE_DEV_API_PROXY_TARGET: "http://127.0.0.1:8080/",
    };

    const target = resolveProxyTarget(env);
    expect(target).toBe("http://127.0.0.1:8080");

    const serverConfig = getViteServerConfig(env);
    const proxy = serverConfig.proxy as Record<string, ProxyRule>;
    expect(proxy["/api"].target).toBe("http://127.0.0.1:8080");
  });

  it("uses external VITE_API_BASE_URL for proxy when configured", () => {
    const externalUrl = "https://custom-codespace-8000.app.github.dev";
    const env = {
      VITE_API_BASE_URL: externalUrl,
      VITE_DEV_API_PROXY_TARGET: "http://127.0.0.1:8000",
    };

    const target = resolveProxyTarget(env);
    expect(target).toBe(externalUrl);

    const serverConfig = getViteServerConfig(env);
    const proxy = serverConfig.proxy as Record<string, ProxyRule>;
    expect(proxy["/api"].target).toBe(externalUrl);
  });

  it("proves local client relative API calls resolve to /api endpoints", () => {
    // When VITE_API_BASE_URL is empty, api-client returns relative paths that Vite proxies
    const originalEnv = import.meta.env.VITE_API_BASE_URL;
    try {
      (import.meta.env as Record<string, unknown>).VITE_API_BASE_URL = "";
      expect(getApiBaseUrl()).toBe("");
      expect(resolveApiUrl("/api/v1/health")).toBe("/api/v1/health");
      expect(resolveApiUrl("/api/v1/ready")).toBe("/api/v1/ready");
      expect(resolveApiUrl("/api/v1/runs")).toBe("/api/v1/runs");
    } finally {
      (import.meta.env as Record<string, unknown>).VITE_API_BASE_URL = originalEnv;
    }
  });

  it("verifies Docker nginx configuration proxies /api/ to api:8000", async () => {
    // Verify docker nginx.conf rule parity
    const fs = await import("fs");
    const path = await import("path");
    const nginxConfPath = path.resolve(__dirname, "../../nginx.conf");
    const nginxContent = fs.readFileSync(nginxConfPath, "utf-8");

    expect(nginxContent).toContain("location /api/ {");
    expect(nginxContent).toContain("proxy_pass http://api:8000;");
  });
});
