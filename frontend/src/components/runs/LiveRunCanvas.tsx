import { Link } from "react-router-dom";
import { ArrowLeft, X } from "lucide-react";
import { PerceptionOverlay } from "./PerceptionOverlay";
import { RunStatusBadge } from "./RunStatusBadge";
import { useRunDetail } from "@/hooks/use-run-detail";
import { useRunMonitor } from "@/hooks/use-run-monitor";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration, formatDateTime, truncate } from "@/lib/utils";
import type { PerceptionFrame } from "@/types/perception";

interface LiveRunCanvasProps {
  runId: string;
}

/**
 * Live Run canvas — the full-bleed dark canvas for the signature visual moment.
 *
 * Uses the RunEventSource (polling) abstraction to update in real-time.
 * The PerceptionOverlay will show real data once the backend persists frames.
 */
export function LiveRunCanvas({ runId }: LiveRunCanvasProps) {
  const { data: run, isLoading } = useRunDetail(runId);
  useRunMonitor(runId);

  const isRunning = run?.status === "running" || run?.status === "queued";

  // Perception frame — backend does not currently persist these, so frame is undefined.
  // The PerceptionOverlay renders its "Perception data unavailable" state gracefully.
  const currentFrame: PerceptionFrame | undefined = undefined;

  return (
    <div className="fixed inset-0 flex flex-col bg-graphite-950">
      {/* Top chrome */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-graphite-600 bg-graphite-800 px-4">
        <div className="flex items-center gap-3">
          <Link
            to="/runs"
            className="flex items-center gap-1.5 text-xs text-ink-400 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
            aria-label="Back to runs"
          >
            <ArrowLeft size={14} aria-hidden="true" />
            Runs
          </Link>
          <span className="text-graphite-600" aria-hidden="true">/</span>
          {isLoading ? (
            <Skeleton className="h-4 w-32" />
          ) : run ? (
            <span className="font-mono text-xs text-ink-400" title={run.id}>
              {run.id.slice(0, 8)}…
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-3">
          {run && <RunStatusBadge status={run.status} withDot />}
          <Link to="/runs" aria-label="Close run view">
            <Button variant="ghost" size="icon">
              <X size={16} />
            </Button>
          </Link>
        </div>
      </div>

      {/* Main area: Perception Overlay (2/3) + sidebar (1/3) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Perception Overlay — full-bleed dark canvas */}
        <div className="relative flex-1 overflow-hidden bg-graphite-950">
          <PerceptionOverlay frame={currentFrame} isLive={isRunning} />
        </div>

        {/* Run info sidebar */}
        <aside className="flex w-72 shrink-0 flex-col border-l border-graphite-600 bg-graphite-800 overflow-y-auto">
          {isLoading ? (
            <div className="p-4 flex flex-col gap-3">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ) : run ? (
            <div className="p-4 flex flex-col gap-5">
              {/* Goal */}
              <div>
                <p className="data-label mb-1">Goal</p>
                <p className="text-sm text-ink-100">{run.goal}</p>
              </div>

              {/* Run metadata */}
              <div className="flex flex-col gap-3">
                <div>
                  <p className="data-label mb-0.5">Run ID</p>
                  <p className="font-mono text-xs text-ink-400">{run.id}</p>
                </div>
                <div>
                  <p className="data-label mb-0.5">Started</p>
                  <p className="font-mono text-xs text-ink-400">
                    {formatDateTime(run.start_time)}
                  </p>
                </div>
                {run.end_time && (
                  <div>
                    <p className="data-label mb-0.5">Completed</p>
                    <p className="font-mono text-xs text-ink-400">
                      {formatDateTime(run.end_time)}
                    </p>
                  </div>
                )}
                <div>
                  <p className="data-label mb-0.5">Duration</p>
                  <p className="font-mono text-xs text-ink-400">
                    {formatDuration(run.duration_seconds)}
                  </p>
                </div>
                <div>
                  <p className="data-label mb-0.5">Defects Found</p>
                  <p
                    className={`font-mono text-sm font-medium ${
                      run.defect_count > 0 ? "text-amber-500" : "text-ink-400"
                    }`}
                  >
                    {run.defect_count}
                  </p>
                </div>
                {run.requester_id && (
                  <div>
                    <p className="data-label mb-0.5">Requested by</p>
                    <p className="font-mono text-xs text-ink-400" title={run.requester_id}>
                      {truncate(run.requester_id, 20)}
                    </p>
                  </div>
                )}
              </div>

              {/* Perception notice */}
              <div className="rounded border border-graphite-600 bg-graphite-950/50 p-3">
                <p className="font-mono text-2xs text-ink-600">
                  Perception frames are not yet persisted by the backend. The overlay will
                  show live grounding data once{" "}
                  <code className="font-mono">PerceptionFrame</code> storage is implemented.
                </p>
              </div>

              {/* Polling indicator */}
              {isRunning && (
                <div className="flex items-center gap-2 text-2xs text-ink-600">
                  <span
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal-teal"
                    aria-hidden="true"
                  />
                  <span className="font-mono">Polling every 3s</span>
                </div>
              )}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
