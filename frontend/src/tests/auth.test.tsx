import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as authStore from "@/lib/auth-store";

describe("auth store", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("returns null when no token is stored", () => {
    expect(authStore.getToken()).toBeNull();
  });

  it("stores and retrieves a token", () => {
    authStore.setToken("test.token.123");
    expect(authStore.getToken()).toBe("test.token.123");
  });

  it("clears the token", () => {
    authStore.setToken("test.token.123");
    authStore.clearToken();
    expect(authStore.getToken()).toBeNull();
  });

  it("isAuthenticated returns false when no token", () => {
    expect(authStore.isAuthenticated()).toBe(false);
  });

  it("decodeToken returns null for invalid token", () => {
    expect(authStore.decodeToken("not.a.token")).toBeNull();
  });
});

describe("ProtectedRoute", () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.clear();
  });

  it("redirects unauthenticated users to /login", async () => {
    const { ProtectedRoute } = await import("@/components/auth/ProtectedRoute");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: 0 } } });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <div>Protected content</div>
                </ProtectedRoute>
              }
            />
            <Route path="/login" element={<div>Login page</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});
