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
}

export function MetricCard({ title, value, subtitle, icon: Icon, isLoading, blocked }: MetricCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <Icon size={14} className="text-ink-600" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-24" />
        ) : blocked ? (
          <div>
            <p className="font-mono text-xs text-ink-600">Not yet available</p>
            <p className="mt-1 text-2xs text-ink-600">Requires additional backend instrumentation</p>
          </div>
        ) : (
          <div>
            <p className="font-mono text-2xl font-medium text-ink-100">{value}</p>
            {subtitle && <p className="mt-1 font-mono text-xs text-ink-400">{subtitle}</p>}
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
      />
      <MetricCard
        title="Avg Run Duration"
        value={isLoading ? "—" : formatDuration(metrics?.average_duration_seconds ?? null)}
        icon={Clock}
        isLoading={isLoading}
      />
      <MetricCard
        title="Detection Rate"
        value="—"
        icon={TrendingUp}
        blocked
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
      className={`flex items-start gap-3 rounded border border-graphite-600 bg-graphite-800 p-4 ${className ?? ""}`}
    >
      <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
      <div>
        <p className="text-sm font-medium text-ink-100">
          Some metrics require additional backend instrumentation
        </p>
        <p className="mt-1 text-xs text-ink-400">
          Defect detection rate, false positive/negative rate, vision-fallback rate, and cost per
          run are not yet available from the backend{" "}
          <code className="font-mono">/api/v1/metrics</code> endpoint. They will appear here once
          the backend exposes them.
        </p>
      </div>
    </div>
  );
}
