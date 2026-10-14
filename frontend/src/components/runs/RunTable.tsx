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
        <p className="text-sm text-body">No runs match your filters.</p>
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
                <span
                  className="rounded bg-canvas px-1.5 py-0.5 font-mono text-xs text-body"
                  title={run.id}
                >
                  {run.id.slice(0, 8)}…
                </span>
              </TableCell>
              <TableCell>
                <Link
                  to={`/runs/${run.id}`}
                  className="block max-w-md truncate text-sm font-medium text-ink hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  title={run.goal}
                >
                  {truncate(run.goal, 60)}
                </Link>
              </TableCell>
              <TableCell>
                <RunStatusBadge status={run.status} withDot />
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-body">
                  {formatDateTime(run.start_time)}
                </span>
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-body">
                  {formatDuration(run.duration_seconds)}
                </span>
              </TableCell>
              <TableCell>
                <span
                  className={`font-mono text-sm font-medium ${
                    run.defect_count > 0 ? "text-status-blocked" : "text-faint"
                  }`}
                >
                  {run.defect_count}
                </span>
              </TableCell>
              <TableCell>
                <Link
                  to={`/runs/${run.id}`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
