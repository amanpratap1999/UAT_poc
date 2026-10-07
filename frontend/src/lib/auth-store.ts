/**
 * Auth token storage.
 *
 * Uses sessionStorage rather than localStorage:
 * - Token is cleared when the browser tab/session is closed
 * - Not accessible from other tabs (isolation)
 * - Acceptable for a QA tool used in controlled enterprise environments
 *
 * NEVER store backend secrets (JWT signing key, API keys, passwords) here.
 */

const TOKEN_KEY = "qa_engine_access_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;
  // Basic expiry check by decoding the JWT payload (no signature verification)
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (payload.exp && Date.now() / 1000 > payload.exp) {
      clearToken();
      return false;
    }
    return true;
  } catch {
    return true; // If we can't decode, assume still valid — server will reject if not
  }
}

/**
 * Decode the JWT payload without verifying signature.
 * Signature verification is the server's job; we only read claims for UI purposes.
 */
export function decodeToken(token: string): Record<string, unknown> | null {
  try {
    return JSON.parse(atob(token.split(".")[1])) as Record<string, unknown>;
  } catch {
    return null;
  }
}
