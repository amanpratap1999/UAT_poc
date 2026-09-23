import { useState, useEffect } from "react";
import { Shield, AlertTriangle, CheckCircle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api-client";

interface SafetyConfig {
  budgets: {
    max_actions: number;
    max_records: number;
    max_tables: number;
    max_destructive: number;
    max_run_time_seconds: number;
    max_mutations: number;
  };
  budget_state: Record<string, number | boolean | string | null>;
  allowed_hosts: string[];
  allowed_instances: string[];
  is_subproduction: boolean;
  allow_mutations: boolean;
  is_safe: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
}

export default function Safety() {
  const [config, setConfig] = useState<SafetyConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSafety(signal: AbortSignal) {
      try {
        setConfig(await api.get<SafetyConfig>("/api/v1/safety", signal));
      } catch (e) {
        if (e instanceof ApiError) setError(e.message);
        else if (!(e instanceof DOMException && e.name === "AbortError")) setError("Unable to load safety configuration.");
      } finally {
        setLoading(false);
      }
    }
    const controller = new AbortController();
    void fetchSafety(controller.signal);
    return () => controller.abort();
  }, []);

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div>
        <h1 className="page-title">Mutation Safety</h1>
        <p className="page-subtitle">Read-only view of runtime safety boundaries and allowed hosts.</p>
      </div>

      {loading ? (
        <div className="surface-card p-5 space-y-4">
          <Skeleton className="h-6 w-1/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : error ? (
        <p className="text-status-failed">{error}</p>
      ) : config ? (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Status Panel */}
          <div className="surface-card p-6 flex flex-col items-center justify-center text-center gap-4">
            <div className={`p-4 rounded-full ${config.is_safe ? 'bg-signal-teal/10 text-signal-teal' : 'bg-status-failed/10 text-status-failed'}`}>
              <Shield size={48} />
            </div>
            <div>
              <h2 className="text-xl font-display font-semibold text-ink-100">
                {config.is_safe ? "Safe Mode Active" : "Mutations Blocked"}
              </h2>
              <p className="text-ink-400 mt-2">
                {config.is_safe
                  ? "Mutations are enabled only for the verified subproduction allowlist."
                  : config.kill_switch_active
                  ? config.kill_switch_reason || "A kill switch is active."
                  : "Mutations are blocked until subproduction, allow_mutations, and an exact allowlist are configured."}
              </p>
            </div>
          </div>

          {/* Configuration */}
          <div className="flex flex-col gap-4">
            <div className="surface-card p-5">
              <h3 className="text-sm font-semibold text-ink-100 mb-4 flex items-center gap-2">
                <AlertTriangle size={16} className="text-status-warning" />
                Allowed Hosts
              </h3>
              <p className="mb-2 text-xs text-ink-500">Mutation allowlist</p>
              {config.allowed_instances.length > 0 ? (
                <ul className="space-y-2">
                  {config.allowed_instances.map(host => (
                    <li key={host} className="text-sm font-mono text-ink-300 bg-graphite-800 p-2 rounded border border-graphite-600">
                      {host}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-400">None</p>
              )}
              <p className="mt-4 text-xs text-ink-500">Browser navigation hosts</p>
              <p className="mt-1 text-xs font-mono text-ink-400">{config.allowed_hosts.join(", ") || "None"}</p>
            </div>

            <div className="surface-card p-5">
              <h3 className="text-sm font-semibold text-ink-100 mb-4 flex items-center gap-2">
                <CheckCircle size={16} className="text-signal-teal" />
                Mutation Budgets
              </h3>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Max Actions</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_actions}</p>
                </div>
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Max Records</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_records}</p>
                </div>
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Max Mutations</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_mutations}</p>
                </div>
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Max Tables</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_tables}</p>
                </div>
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Max Destructive</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_destructive}</p>
                </div>
                <div className="bg-graphite-900 border border-graphite-600 rounded-lg p-3 text-center">
                  <p className="text-xs text-ink-400 font-mono uppercase">Runtime Seconds</p>
                  <p className="text-2xl font-display font-bold text-ink-100 mt-1">{config.budgets.max_run_time_seconds}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-status-failed">Failed to load safety configuration.</p>
      )}
    </div>
  );
}
