import { useState } from "react";
import { AlertTriangle, Filter } from "lucide-react";
import { useFindings } from "@/hooks/use-findings";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { Skeleton } from "@/components/ui/skeleton";
import { classifyCapability } from "@/types/finding";
import type { AnomalyClassification } from "@/types/finding";

const ALL_CLASSIFICATIONS: (AnomalyClassification | "all")[] = [
  "all",
  "Business Rule Failure",
  "Application Bug",
  "Configuration Difference",
  "Expected Customization",
  "Unknown",
];

const SHORT_LABELS: Record<AnomalyClassification | "all", string> = {
  all: "All",
  "Business Rule Failure": "Business Rule",
  "Application Bug": "App Bug",
  "Configuration Difference": "Config Diff",
  "Expected Customization": "Expected",
  Unknown: "Unknown",
};

export default function Findings() {
  const { data: findings, isLoading, error } = useFindings();
  const [classFilter, setClassFilter] = useState<AnomalyClassification | "all">("all");
  const [defectsOnly, setDefectsOnly] = useState(false);

  const filtered = (findings ?? []).filter((f) => {
    if (defectsOnly && !f.is_defect) return false;
    if (classFilter !== "all" && classifyCapability(f.capability) !== classFilter) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
            Findings
          </h1>
          <p className="mt-1 text-sm text-ink-400">
            Review and classify agent-discovered defects and anomalies
          </p>
        </div>
        {findings && (
          <div className="flex items-center gap-2 text-sm text-ink-400">
            <AlertTriangle size={14} className="text-amber-500" aria-hidden="true" />
            <span className="font-mono">
              {findings.filter((f) => f.is_defect).length} defects
            </span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-ink-400">
          <Filter size={12} aria-hidden="true" />
          <span className="font-mono uppercase tracking-wider">Filter</span>
        </div>

        {/* Classification filter */}
        <div className="flex gap-1" role="group" aria-label="Filter by classification">
          {ALL_CLASSIFICATIONS.map((cls) => (
            <button
              key={cls}
              onClick={() => setClassFilter(cls)}
              className={`rounded px-2.5 py-1 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal ${
                classFilter === cls
                  ? "bg-graphite-600 text-ink-100"
                  : "text-ink-400 hover:bg-graphite-800 hover:text-ink-100"
              }`}
              aria-pressed={classFilter === cls}
            >
              {SHORT_LABELS[cls]}
              {cls !== "all" && findings && (
                <span className="ml-1 opacity-60">
                  ({findings.filter((f) => classifyCapability(f.capability) === cls).length})
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Defects only toggle */}
        <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-400">
          <input
            type="checkbox"
            id="defects-only-filter"
            checked={defectsOnly}
            onChange={(e) => setDefectsOnly(e.target.checked)}
            className="accent-amber-500"
          />
          Defects only
        </label>
      </div>

      {/* NOTE: Confirm/override actions are BLOCKED — backend does not expose a PATCH /findings endpoint.
          The read-only review UI is implemented here. Once the backend adds mutation support,
          wire it through a useMutation hook in FindingsTable. */}
      <div className="flex items-start gap-2 rounded border border-graphite-600 bg-graphite-800/50 px-4 py-3 text-xs text-ink-400">
        <span className="shrink-0 font-mono uppercase tracking-wider text-ink-600">Note</span>
        <p>
          Confirm/override actions are read-only in this release.{" "}
          <code className="font-mono">PATCH /api/v1/findings/:id</code> does not yet exist
          in the backend. Override support will be enabled once the endpoint is implemented.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div role="alert" className="rounded border border-status-failed/30 bg-status-failed/10 p-4 text-sm text-status-failed">
          Unable to load findings: {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="surface-card p-0 overflow-hidden">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-graphite-600 px-4 py-3">
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-4 w-28" />
            </div>
          ))}
        </div>
      ) : (
        <FindingsTable findings={filtered} />
      )}
    </div>
  );
}
