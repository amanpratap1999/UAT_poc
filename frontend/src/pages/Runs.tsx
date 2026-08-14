import { useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RunTable } from "@/components/runs/RunTable";
import { NewRunDialog } from "@/components/runs/NewRunDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useRuns } from "@/hooks/use-runs";
import type { RunStatus } from "@/types/run";

const STATUS_FILTERS: { label: string; value: RunStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Running", value: "running" },
  { label: "Queued", value: "queued" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
];

export default function Runs() {
  const { data: runs, isLoading, refetch, isFetching } = useRuns();
  const [statusFilter, setStatusFilter] = useState<RunStatus | "all">("all");
  const [dialogOpen, setDialogOpen] = useState(false);

  const filteredRuns = statusFilter === "all"
    ? (runs ?? [])
    : (runs ?? []).filter((r) => r.status === statusFilter);

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
            Runs
          </h1>
          <p className="mt-1 text-sm text-ink-400">
            History of all QA runs for your workspace
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void refetch()}
            isLoading={isFetching}
            aria-label="Refresh runs"
          >
            <RefreshCw size={16} />
          </Button>
          <Button
            id="new-run-button"
            variant="primary"
            size="md"
            onClick={() => setDialogOpen(true)}
            className="gap-2"
          >
            <Plus size={16} aria-hidden="true" />
            New run
          </Button>
        </div>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1" role="tablist" aria-label="Filter runs by status">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            role="tab"
            id={`status-filter-${f.value}`}
            aria-selected={statusFilter === f.value}
            onClick={() => setStatusFilter(f.value)}
            className={`rounded px-3 py-1.5 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal ${
              statusFilter === f.value
                ? "bg-graphite-600 text-ink-100"
                : "text-ink-400 hover:bg-graphite-800 hover:text-ink-100"
            }`}
          >
            {f.label}
            {f.value !== "all" && runs && (
              <span className="ml-1.5 opacity-60">
                ({runs.filter((r) => r.status === f.value).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Runs table */}
      {isLoading ? (
        <div className="surface-card p-0 overflow-hidden">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-graphite-600 px-4 py-3">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-4 w-28" />
            </div>
          ))}
        </div>
      ) : (
        <RunTable runs={filteredRuns} />
      )}

      {/* Empty state for all runs */}
      {!isLoading && (!runs || runs.length === 0) && (
        <div className="surface-card flex flex-col items-center gap-4 py-14 text-center">
          <p className="text-sm text-ink-400">No runs yet for this workspace.</p>
          <Button
            variant="primary"
            onClick={() => setDialogOpen(true)}
            className="gap-2"
          >
            <Plus size={16} aria-hidden="true" />
            Start your first run
          </Button>
        </div>
      )}

      <NewRunDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}
