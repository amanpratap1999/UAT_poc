import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Zap, AlertCircle, Eye, ScanSearch, ShieldCheck } from "lucide-react";
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
    <div className="flex min-h-screen bg-canvas">
      {/* ── Brand panel (dark) — hidden on small screens ──────────────── */}
      <div
        className="theme-dark relative hidden w-[42%] flex-col justify-between overflow-hidden bg-graphite-950 p-10 lg:flex"
        aria-hidden="true"
      >
        {/* Dot-grid texture — instrument paper, dark */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: "radial-gradient(rgba(232,230,225,0.05) 1px, transparent 1px)",
            backgroundSize: "24px 24px",
          }}
        />

        {/* Product mark */}
        <div className="relative flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-signal-teal/10 ring-1 ring-signal-teal/25">
            <Zap size={18} className="text-signal-teal" />
          </div>
          <div>
            <p className="font-display text-base font-semibold text-ink-100">QA Engine</p>
            <p className="font-mono text-2xs uppercase tracking-[0.16em] text-ink-600">
              Autonomous ServiceNow QA
            </p>
          </div>
        </div>

        {/* Value proposition */}
        <div className="relative flex flex-col gap-8">
          <h2
            className="font-display text-4xl font-semibold leading-tight tracking-tight text-ink-100"
            style={{ maxWidth: "22ch" }}
          >
            An AI agent that tests your ServiceNow like a human would.
          </h2>
          <ul role="list" className="flex flex-col gap-5">
            {[
              {
                icon: ScanSearch,
                title: "Sees the screen",
                text: "Perception-grounded targeting with confidence scores on every element.",
              },
              {
                icon: Eye,
                title: "Shows its work",
                text: "Every action captured as replayable evidence you can audit.",
              },
              {
                icon: ShieldCheck,
                title: "Earns trust",
                text: "Classified findings with human override — nothing ships unreviewed.",
              },
            ].map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex items-start gap-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-graphite-600 bg-graphite-800">
                  <Icon size={17} className="text-signal-teal/90" />
                </div>
                <div>
                  <p className="font-body text-sm font-medium text-ink-100">{title}</p>
                  <p className="mt-0.5 max-w-[38ch] font-body text-xs leading-relaxed text-ink-400">
                    {text}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Footer line */}
        <p className="relative font-mono text-2xs text-ink-600">
          Enterprise-ready · Deterministic knowledge model · Human-in-the-loop gates
        </p>
      </div>

      {/* ── Form panel (light) ─────────────────────────────────────────── */}
      <div className="flex flex-1 items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          {/* Mobile brand mark */}
          <div className="mb-10 flex flex-col items-center gap-3 lg:hidden">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-ink text-canvas shadow-raise">
              <Zap size={22} aria-hidden="true" />
            </div>
            <div className="text-center">
              <h1 className="page-title">QA Engine</h1>
              <p className="page-subtitle">
                Autonomous ServiceNow Quality Assurance
              </p>
            </div>
          </div>

          {/* Login form */}
          <form
            onSubmit={handleSubmit}
            className="surface-elevated flex flex-col gap-4 p-6 sm:p-8"
            aria-label="Sign in form"
            noValidate
          >
            <h2 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted">
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
                className="flex items-start gap-2 rounded-md border border-status-failed/30 bg-status-failed/5 p-3 text-sm text-status-failed"
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
          <p className="mt-4 text-center text-xs text-faint">
            Contact your QA Manager or system administrator if you've lost access.
          </p>
        </div>
      </div>
    </div>
  );
}
