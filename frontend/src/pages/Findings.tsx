import { useState } from "react";
import { AlertTriangle, Filter } from "lucide-react";
import { useFindings } from "@/hooks/use-findings";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { Skeleton } from "@/components/ui/skeleton";
import { classifyCapability } from "@/types/finding";
import type { AnomalyClassification } from "@/types/finding";

const ALL_CLASSIFICATIONS: (AnomalyClassification | "all")[] = [
  "all",
  "Application Bug",
  "Business Rule Failure",
  "Configuration Difference",
  "Expected Customization",
  "Agent Issue",
  "Unknown",
];

const SHORT_LABELS: Record<AnomalyClassification | "all", string> = {
  all: "All",
  "Business Rule Failure": "Business Rule",
  "Application Bug": "App Bug",
  "Configuration Difference": "Config Diff",
  "Expected Customization": "Expected",
  "Agent Issue": "Agent Issue",
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
          <h1 className="page-title">Findings</h1>
          <p className="page-subtitle">
            Review and classify agent-discovered defects and anomalies
          </p>
        </div>
        {findings && (
          <div className="flex items-center gap-2 rounded-full border border-status-blocked/25 bg-status-blocked/[0.08] px-3 py-1 text-sm text-status-blocked">
            <AlertTriangle size={13} aria-hidden="true" />
            <span className="font-mono text-xs font-medium">
              {findings.filter((f) => f.is_defect).length} defects
            </span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <Filter size={12} aria-hidden="true" />
          <span className="font-mono uppercase tracking-wider">Filter</span>
        </div>

        {/* Classification filter */}
        <div
          className="inline-flex flex-wrap items-center gap-1 rounded-lg border border-line bg-card p-1 shadow-card"
          role="group"
          aria-label="Filter by classification"
        >
          {ALL_CLASSIFICATIONS.map((cls) => (
            <button
              key={cls}
              onClick={() => setClassFilter(cls)}
              className={`rounded-md px-2.5 py-1 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                classFilter === cls
                  ? "bg-ink text-canvas shadow-card"
                  : "text-muted hover:bg-ink/5 hover:text-ink"
              }`}
              aria-pressed={classFilter === cls}
            >
              {SHORT_LABELS[cls]}
              {cls !== "all" && findings && (
                <span className={`ml-1 ${classFilter === cls ? "opacity-60" : "opacity-70"}`}>
                  ({findings.filter((f) => classifyCapability(f.capability) === cls).length})
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Defects only toggle */}
        <label
          htmlFor="defects-only-filter"
          className="flex cursor-pointer select-none items-center gap-2 rounded-md border border-line bg-card px-3 py-1.5 text-xs text-body shadow-card transition-colors hover:border-line-strong has-[:checked]:border-status-blocked/40 has-[:checked]:bg-status-blocked/5 has-[:checked]:text-status-blocked"
        >
          <input
            type="checkbox"
            id="defects-only-filter"
            checked={defectsOnly}
            onChange={(e) => setDefectsOnly(e.target.checked)}
            className="h-3.5 w-3.5 accent-[rgb(var(--status-blocked))]"
          />
          Defects only
        </label>
      </div>

      {/* NOTE: Confirm/override actions ARE live — PATCH /api/v1/findings/:id.
          Select a row to open the override panel (classification + defect flag). */}
      <div className="flex items-start gap-2 rounded-lg border border-dashed border-line bg-card/50 px-4 py-3 text-xs text-body">
        <span className="shrink-0 font-mono uppercase tracking-wider text-faint">Tip</span>
        <p>
          Select a finding to review evidence and override its classification or defect flag —
          changes persist via <code className="rounded bg-canvas px-1 py-0.5 font-mono text-2xs">PATCH /api/v1/findings/:id</code> and
          feed the human-reviewed baseline.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div role="alert" className="rounded-lg border border-status-failed/30 bg-status-failed/5 p-4 text-sm text-status-failed">
          Unable to load findings: {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="surface-card overflow-hidden p-0">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-line px-4 py-3">
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
