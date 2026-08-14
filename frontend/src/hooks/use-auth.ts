import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "@/lib/api-client";
import { getToken, setToken, clearToken, isAuthenticated, decodeToken } from "@/lib/auth-store";
import type { TokenResponse, UserContext, UserRole } from "@/types/auth";

function parseUserContext(token: string): UserContext | null {
  const payload = decodeToken(token);
  if (!payload) return null;
  return {
    username: String(payload.sub ?? ""),
    role: String(payload.role ?? "Viewer") as UserRole,
    tenant_id: String(payload.tenant_id ?? ""),
    user_id: String(payload.user_id ?? ""),
  };
}

export function useAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [user, setUser] = useState<UserContext | null>(() => {
    const token = getToken();
    if (token && isAuthenticated()) return parseUserContext(token);
    return null;
  });

  // Sync user state if token changes externally (e.g. expiry)
  useEffect(() => {
    const token = getToken();
    if (token && isAuthenticated()) {
      setUser(parseUserContext(token));
    } else if (!isAuthenticated()) {
      setUser(null);
    }
  }, []);

  const loginMutation = useMutation({
    mutationFn: async ({ username, password }: { username: string; password: string }) => {
      const response = await api.postForm<TokenResponse>("/api/v1/token", {
        username,
        password,
        grant_type: "password",
      });
      return response;
    },
    onSuccess: (data) => {
      setToken(data.access_token);
      const ctx = parseUserContext(data.access_token);
      setUser(ctx);
      void queryClient.invalidateQueries();
      navigate("/", { replace: true });
    },
  });

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    queryClient.clear();
    navigate("/login", { replace: true });
  }, [navigate, queryClient]);

  return {
    user,
    isAuthenticated: !!user,
    login: loginMutation.mutate,
    loginAsync: loginMutation.mutateAsync,
    isLoggingIn: loginMutation.isPending,
    loginError: loginMutation.error instanceof ApiError
      ? loginMutation.error.message
      : loginMutation.error
        ? "Login failed. Check your credentials and try again."
        : null,
    logout,
  };
}
