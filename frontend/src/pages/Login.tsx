import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Zap, AlertCircle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isAuthenticated } from "@/lib/auth-store";

export default function Login() {
  const { login, isLoggingIn, loginError } = useAuth();
  const location = useLocation();
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Already authenticated — redirect
  if (isAuthenticated()) {
    return <Navigate to={from} replace />;
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    login({ username: username.trim(), password });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-graphite-950 px-4">
      <div className="w-full max-w-sm">
        {/* Product mark */}
        <div className="mb-10 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-graphite-600 bg-graphite-800">
            <Zap size={22} className="text-signal-teal" aria-hidden="true" />
          </div>
          <div className="text-center">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
              QA Engine
            </h1>
            <p className="mt-1 text-sm text-ink-400">
              Autonomous ServiceNow Quality Assurance
            </p>
          </div>
        </div>

        {/* Login form */}
        <form
          onSubmit={handleSubmit}
          className="surface-card flex flex-col gap-4 p-6"
          aria-label="Sign in form"
          noValidate
        >
          <h2 className="font-display text-sm font-semibold uppercase tracking-widest text-ink-400">
            Sign in to your account
          </h2>

          <Input
            id="login-username"
            label="Username"
            type="text"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={isLoggingIn}
            required
            placeholder="admin"
          />

          <Input
            id="login-password"
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isLoggingIn}
            required
            placeholder="••••••••"
          />

          {loginError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded border border-status-failed/30 bg-status-failed/10 p-3 text-sm text-status-failed"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <p>{loginError}</p>
            </div>
          )}

          <Button
            id="login-submit"
            type="submit"
            variant="primary"
            size="md"
            isLoading={isLoggingIn}
            disabled={!username.trim() || !password.trim()}
            className="w-full"
          >
            Sign in
          </Button>
        </form>

        {/* Recovery guidance — Invariant 7 */}
        <p className="mt-4 text-center text-xs text-ink-600">
          Contact your QA Manager or system administrator if you've lost access.
        </p>
      </div>
    </div>
  );
}
