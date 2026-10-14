import { useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Bug, CheckCircle, ChevronDown, ChevronUp } from "lucide-react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { ClassificationBadge } from "./ClassificationBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime, truncate } from "@/lib/utils";
import { useUpdateFinding } from "@/hooks/use-update-finding";
import { CLASSIFICATION_COLORS } from "@/types/finding";
import type { AnomalyClassification, Finding } from "@/types/finding";

interface FindingsTableProps {
  findings: Finding[];
}

const CLASSIFICATION_OPTIONS: AnomalyClassification[] = [
  "Application Bug",
  "Business Rule Failure",
  "Configuration Difference",
  "Expected Customization",
  "Agent Issue",
  "Unknown",
];

export function FindingsTable({ findings }: FindingsTableProps) {
  const [selected, setSelected] = useState<Finding | null>(null);
  const updateFinding = useUpdateFinding();

  if (findings.length === 0) {
    return (
      <div className="surface-card flex flex-col items-center gap-3 py-12 text-center">
        <CheckCircle size={24} className="text-status-completed" aria-hidden="true" />
        <p className="text-sm text-ink">No findings match your filters.</p>
        <p className="text-xs text-body">
          If you expect findings, ensure runs have completed and produced results.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden p-0">
      <Table aria-label="Findings">
        <TableHeader>
          <TableRow>
            <TableHead>Classification</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Defect</TableHead>
            <TableHead>Run</TableHead>
            <TableHead>Found</TableHead>
            <TableHead>
              <span className="sr-only">View run</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((finding) => (
            <TableRow
              key={finding.id}
              className={selected?.id === finding.id ? "bg-accent-soft" : undefined}
              onClick={() => setSelected(selected?.id === finding.id ? null : finding)}
              style={{ cursor: "pointer" }}
            >
              <TableCell>
                <ClassificationBadge capability={finding.capability} />
              </TableCell>
              <TableCell>
                <span className="block max-w-md truncate text-sm text-ink" title={finding.description}>
                  {truncate(finding.description, 80)}
                </span>
              </TableCell>
              <TableCell>
                {finding.severity ? (
                  <Badge
                    variant={finding.severity.toLowerCase() === "high" || finding.severity.toLowerCase() === "critical" ? "failed" : "default"}
                    className="capitalize"
                  >
                    {finding.severity}
                  </Badge>
                ) : (
                  <span className="text-xs text-faint">—</span>
                )}
              </TableCell>
              <TableCell>
                {finding.is_defect ? (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full border border-status-blocked/30 bg-status-blocked/10 px-2 py-0.5 font-mono text-2xs font-medium text-status-blocked"
                    title="Defect"
                  >
                    <Bug size={11} aria-label="Defect" />
                    Defect
                  </span>
                ) : (
                  <span className="text-xs text-faint">—</span>
                )}
              </TableCell>
              <TableCell>
                <span
                  className="rounded bg-canvas px-1.5 py-0.5 font-mono text-xs text-body"
                  title={finding.run_id}
                >
                  {finding.run_id.slice(0, 8)}…
                </span>
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-body">
                  {formatDateTime(finding.created_at)}
                </span>
              </TableCell>
              <TableCell>
                <Link
                  to={`/runs/${finding.run_id}`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  aria-label={`View run ${finding.run_id.slice(0, 8)}`}
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink size={14} aria-hidden="true" />
                  Run
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Selected finding detail / override panel */}
      {selected && (
        <div className="border-t border-line bg-canvas/70 p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="data-label mb-1.5">Description</p>
              <p className="text-sm leading-relaxed text-ink break-words">{selected.description}</p>
              <p className="mt-3 rounded bg-card px-2 py-1 font-mono text-2xs text-faint inline-block">
                Finding ID: {selected.id}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSelected(null)}
              aria-label="Close detail"
            >
              {selected ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </Button>
          </div>

          {/* Override controls */}
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <span className="data-label">Override classification</span>
            {CLASSIFICATION_OPTIONS.map((cls) => {
              const active = selected.capability === cls;
              return (
                <button
                  key={cls}
                  onClick={() =>
                    updateFinding.mutate({
                      id: selected.id,
                      update: { capability: cls },
                    })
                  }
                  disabled={active || updateFinding.isPending}
                  className="rounded-full border px-2.5 py-1 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-40"
                  style={{
                    color: active ? "rgb(var(--card))" : CLASSIFICATION_COLORS[cls],
                    backgroundColor: active ? CLASSIFICATION_COLORS[cls] : undefined,
                    borderColor: active ? CLASSIFICATION_COLORS[cls] : "rgb(var(--class-unknown) / 0.35)",
                  }}
                  aria-pressed={active}
                >
                  {cls}
                </button>
              );
            })}

            <span className="ml-4 data-label">Defect</span>
            <Button
              variant={selected.is_defect ? "primary" : "outline"}
              size="sm"
              onClick={() =>
                updateFinding.mutate({
                  id: selected.id,
                  update: { is_defect: !selected.is_defect },
                })
              }
              disabled={updateFinding.isPending}
            >
              {selected.is_defect ? "Confirmed defect" : "Mark as defect"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                updateFinding.mutate({
                  id: selected.id,
                  update: { is_defect: false },
                })
              }
              disabled={!selected.is_defect || updateFinding.isPending}
            >
              Clear defect flag
            </Button>

            {updateFinding.isPending && (
              <span className="font-mono text-2xs text-faint">Saving…</span>
            )}
            {updateFinding.isError && (
              <span role="alert" className="font-mono text-2xs text-status-failed">
                Failed to update:{" "}
                {updateFinding.error instanceof Error
                  ? updateFinding.error.message
                  : "unknown error"}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
