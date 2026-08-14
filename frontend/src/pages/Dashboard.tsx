import { useMetrics } from "@/hooks/use-metrics";
import { useRuns } from "@/hooks/use-runs";
import { MetricsGrid, BlockedMetricsBanner } from "@/components/dashboard/MetricsGrid";
import { RunTrendChart } from "@/components/dashboard/RunTrendChart";
import { DashboardEmpty } from "@/components/dashboard/DashboardEmpty";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle } from "lucide-react";

export default function Dashboard() {
  const { data: metrics, isLoading: metricsLoading, error: metricsError } = useMetrics();
  const { data: runs, isLoading: runsLoading } = useRuns();

  const noRuns = !runsLoading && (!runs || runs.length === 0);
  const isLoading = metricsLoading || runsLoading;

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Page heading */}
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-ink-400">
          Quality metrics for your ServiceNow QA runs
        </p>
      </div>

      {/* Metrics error */}
      {metricsError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded border border-status-failed/30 bg-status-failed/10 p-4 text-sm text-status-failed"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Unable to load metrics</p>
            <p className="mt-1 text-xs opacity-80">
              {metricsError instanceof Error ? metricsError.message : "Check that the backend is running and you have QA Manager or Admin role."}
            </p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {noRuns && !metricsError ? (
        <DashboardEmpty />
      ) : (
        <>
          {/* Metrics grid */}
          {isLoading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="surface-card p-5">
                  <Skeleton className="mb-3 h-3 w-28" />
                  <Skeleton className="h-8 w-20" />
                </div>
              ))}
            </div>
          ) : metrics ? (
            <MetricsGrid metrics={metrics} isLoading={false} />
          ) : null}

          {/* Blocked metrics notice */}
          <BlockedMetricsBanner />

          {/* Trend chart */}
          {runsLoading ? (
            <div className="surface-card p-5">
              <Skeleton className="mb-4 h-4 w-32" />
              <Skeleton className="h-48 w-full" />
            </div>
          ) : runs && runs.length > 0 ? (
            <RunTrendChart runs={runs} />
          ) : null}
        </>
      )}
    </div>
  );
}
