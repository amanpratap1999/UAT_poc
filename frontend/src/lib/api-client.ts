/**
 * Centralized API client.
 *
 * Handles:
 * - Base URL from VITE_API_BASE_URL env var
 * - Authorization: Bearer token injection
 * - JSON serialization/deserialization
 * - Typed error normalization (ApiError)
 * - Request cancellation via AbortSignal
 * - Token expiry detection (401 → clear token + redirect)
 */

import { getToken, clearToken } from "./auth-store";

/**
 * Normalizes and returns the API base URL from the VITE_API_BASE_URL environment variable.
 * Does not fall back to localhost:8000 to ensure Codespaces and custom domains resolve correctly.
 */
export function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (!envUrl || typeof envUrl !== "string") {
    return "";
  }
  return envUrl.trim().replace(/\/+$/, "");
}

/**
 * Resolves a given API path against the configured VITE_API_BASE_URL.
 * E.g., resolveApiUrl("/api/v1/token") -> "${VITE_API_BASE_URL}/api/v1/token" (or "/api/v1/token" if relative).
 */
export function resolveApiUrl(path: string): string {
  const baseUrl = getApiBaseUrl();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return baseUrl ? `${baseUrl}${normalizedPath}` : normalizedPath;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions extends RequestInit {
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const url = resolveApiUrl(path);
  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    clearToken();
    // Let the app detect the token removal and redirect to login
    throw new ApiError(401, "Session expired. Please log in again.");
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, detail);
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}

// ─── Typed API methods ────────────────────────────────────────────────────────

export const api = {
  get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "GET", signal });
  },

  post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    });
  },

  patch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
      signal,
    });
  },

  delete<T>(path: string, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "DELETE", signal });
  },

  /**
   * POST with application/x-www-form-urlencoded encoding.
   * Used for OAuth2 password flow (POST /api/v1/token).
   */
  postForm<T>(path: string, body: Record<string, string>): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/x-www-form-urlencoded",
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const url = resolveApiUrl(path);
    return fetch(url, {
      method: "POST",
      headers,
      body: new URLSearchParams(body).toString(),
    }).then(async (res) => {
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new ApiError(res.status, detail?.detail ?? "Login failed", detail);
      }
      return res.json() as Promise<T>;
    });
  },
};
