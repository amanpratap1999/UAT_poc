import { TrendingUp, Clock, Bug, PlayCircle, AlertCircle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration } from "@/lib/utils";
import type { Metrics } from "@/types/metrics";

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  isLoading?: boolean;
  blocked?: boolean;
  tone?: "neutral" | "warning" | "success";
}

export function MetricCard({ title, value, subtitle, icon: Icon, isLoading, blocked, tone = "neutral" }: MetricCardProps) {
  return (
    <Card className="group relative overflow-hidden p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-raise">
      {/* Tone edge — subtle top hairline accent */}
      <span
        aria-hidden="true"
        className={`absolute inset-x-0 top-0 h-px ${
          tone === "warning"
            ? "bg-status-blocked/50"
            : tone === "success"
            ? "bg-status-completed/50"
            : "bg-transparent"
        }`}
      />
      <CardHeader className="mb-3">
        <CardTitle>{title}</CardTitle>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${
            tone === "warning"
              ? "bg-status-blocked/10 text-status-blocked"
              : tone === "success"
              ? "bg-status-completed/10 text-status-completed"
              : "bg-ink/5 text-muted"
          }`}
        >
          <Icon size={15} aria-hidden="true" />
        </span>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-9 w-24" />
        ) : blocked ? (
          <div>
            <p className="font-mono text-sm text-faint">Not yet available</p>
            <p className="mt-1 text-2xs text-faint">Requires additional backend instrumentation</p>
          </div>
        ) : (
          <div>
            <p className="font-mono text-3xl font-medium tracking-tight text-ink">{value}</p>
            {subtitle && <p className="mt-1.5 text-xs text-muted">{subtitle}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface MetricsGridProps {
  metrics: Metrics;
  isLoading: boolean;
}

export function MetricsGrid({ metrics, isLoading }: MetricsGridProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        title="Total Runs"
        value={isLoading ? "—" : metrics?.total_runs ?? 0}
        subtitle="all time"
        icon={PlayCircle}
        isLoading={isLoading}
      />
      <MetricCard
        title="Total Defects"
        value={isLoading ? "—" : metrics?.total_defects ?? 0}
        subtitle={metrics?.total_runs ? `${((metrics.total_defects / metrics.total_runs)).toFixed(1)} per run` : undefined}
        icon={Bug}
        isLoading={isLoading}
        tone={metrics?.total_defects ? "warning" : "success"}
      />
      <MetricCard
        title="Avg Run Duration"
        value={isLoading ? "—" : formatDuration(metrics?.average_duration_seconds ?? null)}
        icon={Clock}
        isLoading={isLoading}
      />
      <MetricCard
        title="Pass Rate"
        value={metrics?.pass_rate == null ? "—" : `${(metrics.pass_rate * 100).toFixed(1)}%`}
        icon={TrendingUp}
        subtitle={metrics?.terminal_runs ? `${metrics.passed_runs} of ${metrics.terminal_runs} terminal runs` : "no terminal runs"}
        tone={metrics?.pass_rate === 1 ? "success" : metrics?.pass_rate != null ? "warning" : "neutral"}
      />
    </div>
  );
}

interface BlockedMetricsProps {
  className?: string;
}

export function BlockedMetricsBanner({ className }: BlockedMetricsProps) {
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border border-line bg-card p-4 shadow-card ${className ?? ""}`}
    >
      <AlertCircle size={16} className="mt-0.5 shrink-0 text-status-blocked" aria-hidden="true" />
      <div>
        <p className="text-sm font-medium text-ink">
          Some metrics require additional backend instrumentation
        </p>
        <p className="mt-1 text-xs leading-relaxed text-body">
          False positive/negative rate, vision-fallback rate, and cost per run are not yet available from the backend{" "}
          <code className="rounded bg-canvas px-1 py-0.5 font-mono text-2xs text-body">/api/v1/metrics</code> endpoint. They will appear here once
          the backend exposes them.
        </p>
      </div>
    </div>
  );
}
