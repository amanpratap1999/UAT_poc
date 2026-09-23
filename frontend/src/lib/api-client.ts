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

// ─── Binary (blob) fetch with auth ────────────────────────────────────────────

async function fetchBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const url = resolveApiUrl(path);
  const response = await fetch(url, { method: "GET", headers, signal });

  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, "Session expired. Please log in again.");
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text().catch(() => "");
    }
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `Failed to load resource (${response.status})`;
    throw new ApiError(response.status, message, detail);
  }

  const contentType = response.headers.get("content-type") || "";
  const blob = await response.blob();

  if (blob.size === 0) {
    throw new ApiError(response.status, "Received empty screenshot image data");
  }

  if (
    contentType &&
    !contentType.startsWith("image/") &&
    !contentType.includes("application/octet-stream")
  ) {
    throw new ApiError(
      response.status,
      `Expected image response but received ${contentType}`
    );
  }

  return blob;
}

async function fetchBinary(
  path: string,
  method: "GET" | "POST",
  body?: unknown,
  signal?: AbortSignal,
): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(resolveApiUrl(path), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, "Session expired. Please log in again.");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, detail);
  }
  return response.blob();
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
   * GET a binary blob (e.g. a screenshot) with auth headers.
   * Returns a Blob suitable for URL.createObjectURL().
   */
  getBlob(path: string, signal?: AbortSignal): Promise<Blob> {
    return fetchBlob(path, signal);
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

  postMultipart<T>(path: string, formData: FormData, signal?: AbortSignal): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(resolveApiUrl(path), {
      method: "POST",
      headers,
      body: formData,
      signal,
    }).then(async (res) => {
      if (res.status === 401) {
        clearToken();
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        const message =
          typeof detail === "object" && detail !== null && "detail" in detail
            ? String((detail as { detail: unknown }).detail)
            : `Request failed with status ${res.status}`;
        throw new ApiError(res.status, message, detail);
      }
      return res.json() as Promise<T>;
    });
  },

  postBlob(path: string, body: unknown, signal?: AbortSignal): Promise<Blob> {
    return fetchBinary(path, "POST", body, signal);
  },

  // ─── Interactive Agent Controls ──────────────────────────────────────────

  pauseRun(runId: string, reason = "User requested pause"): Promise<{ status: string; message: string }> {
    return this.post(`/api/v1/runs/${runId}/pause`, { reason });
  },

  resumeRun(runId: string, message = "User resumed run"): Promise<{ status: string; message: string }> {
    return this.post(`/api/v1/runs/${runId}/resume`, { message });
  },

  cancelRun(runId: string, reason = "User cancelled run"): Promise<{ status: string; message: string }> {
    return this.post(`/api/v1/runs/${runId}/cancel`, { reason });
  },

  clarifyRun(runId: string, requestId: string, answer: string): Promise<{ status: string; message: string }> {
    return this.post(`/api/v1/runs/${runId}/clarify`, { request_id: requestId, answer });
  },

  approveRun(
    runId: string,
    promptId: string,
    approved: boolean,
    feedback?: string
  ): Promise<{ status: string; message: string }> {
    return this.post(`/api/v1/runs/${runId}/approve`, { prompt_id: promptId, approved, feedback });
  },

  generateTestCases(payload: {
    story?: string;
    requirement?: string;
    acceptance_criteria?: string[];
    table_name?: string;
    workflow_type?: string;
  }): Promise<{ story_id: string; test_cases: any[]; count: number }> {
    return this.post("/api/v1/test-cases/generate", payload);
  },

  importTestCases(
    file: File,
    options: { execute?: boolean; personas?: string[]; sheetName?: string } = {},
  ): Promise<any[]> {
    const form = new FormData();
    form.append("file", file);
    form.append("execute", String(options.execute ?? false));
    if (options.personas?.length) form.append("personas", options.personas.join(","));
    if (options.sheetName) form.append("sheet_name", options.sheetName);
    return this.postMultipart("/api/v1/test-cases/import", form);
  },

  sweepTestCase(testCaseId: string, personas: string[]): Promise<any[]> {
    return this.post(`/api/v1/test-cases/${testCaseId}/sweep`, { personas });
  },

  comparePersonas(testCaseId: string, personas: string[]): Promise<any> {
    return this.post(`/api/v1/test-cases/${testCaseId}/compare-personas`, { personas });
  },

  exportTestCaseResults(runIds: string[]): Promise<Blob> {
    return this.postBlob("/api/v1/test-cases/export-results", runIds);
  },

  executeTestCase(testCaseId: string): Promise<{ session_id: string; status: string; message: string }> {
    return this.post(`/api/v1/test-cases/${testCaseId}/execute`, {});
  },

  getStreamTicket(runId: string): Promise<{ ticket: string }> {
    return this.post(`/api/v1/runs/${runId}/stream-ticket`, {});
  },
};

