import { Link } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { RunStatusBadge } from "./RunStatusBadge";
import { formatDateTime, formatDuration, truncate } from "@/lib/utils";
import type { Run } from "@/types/run";

interface RunTableProps {
  runs: Run[];
}

export function RunTable({ runs }: RunTableProps) {
  if (runs.length === 0) {
    return (
      <div className="surface-card flex flex-col items-center gap-3 py-12 text-center">
        <p className="text-sm text-ink-400">No runs match your filters.</p>
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden p-0">
      <Table aria-label="Run history">
        <TableHeader>
          <TableRow>
            <TableHead>Run ID</TableHead>
            <TableHead>Goal</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Started</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Defects</TableHead>
            <TableHead className="sr-only">View</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              <TableCell>
                <span className="font-mono text-xs text-ink-400" title={run.id}>
                  {run.id.slice(0, 8)}…
                </span>
              </TableCell>
              <TableCell>
                <span className="text-sm text-ink-100" title={run.goal}>
                  {truncate(run.goal, 60)}
                </span>
              </TableCell>
              <TableCell>
                <RunStatusBadge status={run.status} withDot />
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-ink-400">
                  {formatDateTime(run.start_time)}
                </span>
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-ink-400">
                  {formatDuration(run.duration_seconds)}
                </span>
              </TableCell>
              <TableCell>
                <span
                  className={`font-mono text-sm ${
                    run.defect_count > 0 ? "text-amber-500" : "text-ink-400"
                  }`}
                >
                  {run.defect_count}
                </span>
              </TableCell>
              <TableCell>
                <Link
                  to={`/runs/${run.id}`}
                  className="inline-flex items-center gap-1 text-xs text-ink-400 hover:text-signal-teal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
                  aria-label={`View run ${run.id.slice(0, 8)}`}
                >
                  <ExternalLink size={14} aria-hidden="true" />
                  View
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
