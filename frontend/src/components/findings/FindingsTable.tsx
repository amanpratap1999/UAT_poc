import { useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Bug, CheckCircle } from "lucide-react";
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
import { formatDateTime, truncate } from "@/lib/utils";
import type { Finding } from "@/types/finding";

interface FindingsTableProps {
  findings: Finding[];
}

export function FindingsTable({ findings }: FindingsTableProps) {
  const [selected, setSelected] = useState<Finding | null>(null);

  if (findings.length === 0) {
    return (
      <div className="surface-card flex flex-col items-center gap-3 py-12 text-center">
        <CheckCircle size={24} className="text-class-expected-custom" aria-hidden="true" />
        <p className="text-sm text-ink-100">No findings match your filters.</p>
        <p className="text-xs text-ink-400">
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
            <TableHead className="sr-only">View run</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((finding) => (
            <TableRow
              key={finding.id}
              className={selected?.id === finding.id ? "bg-graphite-600/30" : undefined}
              onClick={() => setSelected(selected?.id === finding.id ? null : finding)}
              style={{ cursor: "pointer" }}
            >
              <TableCell>
                <ClassificationBadge capability={finding.capability} />
              </TableCell>
              <TableCell>
                <span className="text-sm text-ink-100" title={finding.description}>
                  {truncate(finding.description, 80)}
                </span>
              </TableCell>
              <TableCell>
                {finding.severity ? (
                  <Badge
                    variant={finding.severity.toLowerCase() === "high" ? "failed" : "default"}
                    className="capitalize"
                  >
                    {finding.severity}
                  </Badge>
                ) : (
                  <span className="text-xs text-ink-600">—</span>
                )}
              </TableCell>
              <TableCell>
                {finding.is_defect ? (
                  <Bug size={14} className="text-amber-500" aria-label="Defect" />
                ) : (
                  <span className="text-xs text-ink-600">—</span>
                )}
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-ink-400" title={finding.run_id}>
                  {finding.run_id.slice(0, 8)}…
                </span>
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-ink-400">
                  {formatDateTime(finding.created_at)}
                </span>
              </TableCell>
              <TableCell>
                <Link
                  to={`/runs/${finding.run_id}`}
                  className="inline-flex items-center gap-1 text-xs text-ink-400 hover:text-signal-teal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
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
    </div>
  );
}
