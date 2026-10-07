import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getApiBaseUrl, resolveApiUrl, api } from "@/lib/api-client";

describe("API Client URL Configuration for Codespaces & Custom Hosts", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns empty string when VITE_API_BASE_URL is not set", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(getApiBaseUrl()).toBe("");
    expect(resolveApiUrl("/api/v1/token")).toBe("/api/v1/token");
    expect(resolveApiUrl("/api/v1/runs")).toBe("/api/v1/runs");
  });

  it("does NOT fall back to localhost:8000 when VITE_API_BASE_URL is empty", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    const resolved = resolveApiUrl("/api/v1/token");
    expect(resolved).not.toContain("localhost");
    expect(resolved).not.toContain("8000");
    expect(resolved).toBe("/api/v1/token");
  });

  it("resolves Codespaces backend URL correctly for authentication and endpoints", () => {
    const codespacesUrl = "https://refactored-space-eureka-7vv9697r9jrhv99-8000.app.github.dev";
    vi.stubEnv("VITE_API_BASE_URL", codespacesUrl);

    expect(getApiBaseUrl()).toBe(codespacesUrl);
    expect(resolveApiUrl("/api/v1/token")).toBe(`${codespacesUrl}/api/v1/token`);
    expect(resolveApiUrl("/api/v1/runs")).toBe(`${codespacesUrl}/api/v1/runs`);
    expect(resolveApiUrl("/api/v1/findings")).toBe(`${codespacesUrl}/api/v1/findings`);
    expect(resolveApiUrl("/api/v1/metrics")).toBe(`${codespacesUrl}/api/v1/metrics`);
    expect(resolveApiUrl("/api/v1/health")).toBe(`${codespacesUrl}/api/v1/health`);
  });

  it("trims trailing slashes from VITE_API_BASE_URL without creating double slashes", () => {
    const codespacesUrlWithSlash = "https://codespaces-backend.app.github.dev/";
    vi.stubEnv("VITE_API_BASE_URL", codespacesUrlWithSlash);

    expect(getApiBaseUrl()).toBe("https://codespaces-backend.app.github.dev");
    expect(resolveApiUrl("/api/v1/token")).toBe("https://codespaces-backend.app.github.dev/api/v1/token");
    expect(resolveApiUrl("api/v1/token")).toBe("https://codespaces-backend.app.github.dev/api/v1/token");
  });

  it("makes login postForm request to the exact Codespaces URL", async () => {
    const codespacesUrl = "https://codespaces-backend.app.github.dev";
    vi.stubEnv("VITE_API_BASE_URL", codespacesUrl);

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "mock-jwt-token", token_type: "bearer" }),
    });
    global.fetch = mockFetch;

    await api.postForm("/api/v1/token", {
      username: "admin",
      password: "password123",
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [calledUrl, calledOptions] = mockFetch.mock.calls[0];
    expect(calledUrl).toBe("https://codespaces-backend.app.github.dev/api/v1/token");
    expect(calledOptions.method).toBe("POST");
    expect(calledOptions.body).toContain("username=admin");
  });

  it("makes GET requests to the exact Codespaces URL", async () => {
    const codespacesUrl = "https://codespaces-backend.app.github.dev";
    vi.stubEnv("VITE_API_BASE_URL", codespacesUrl);

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: "run-1", goal: "Test", status: "completed" }],
    });
    global.fetch = mockFetch;

    await api.get("/api/v1/runs");

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toBe("https://codespaces-backend.app.github.dev/api/v1/runs");
  });
});
