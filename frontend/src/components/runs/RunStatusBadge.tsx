import { Badge } from "@/components/ui/badge";
import type { RunStatus } from "@/types/run";

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
  cancelled: "Cancelled",
};

interface RunStatusBadgeProps {
  status: RunStatus;
  withDot?: boolean;
}

export function RunStatusBadge({ status, withDot }: RunStatusBadgeProps) {
  const variant = status as Parameters<typeof Badge>[0]["variant"];
  return (
    <Badge variant={variant} className="items-center gap-1.5">
      {withDot && status === "running" && (
        <span
          className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-signal-teal"
          aria-hidden="true"
        />
      )}
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
