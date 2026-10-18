import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  X,
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  Square,
  CheckCircle2,
  XCircle,
  AlertCircle,
  AlertTriangle,
  HelpCircle,
  ShieldAlert,
  Loader2,
} from "lucide-react";
import { PerceptionOverlay } from "./PerceptionOverlay";
import { RunStatusBadge } from "./RunStatusBadge";
import { useRunDetail } from "@/hooks/use-run-detail";
import { useRunPerception, evidenceToFrames } from "@/hooks/use-run-perception";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, resolveApiUrl } from "@/lib/api-client";
import { getToken } from "@/lib/auth-store";
import { formatDuration, formatDateTime } from "@/lib/utils";
import type { PerceptionFrame } from "@/types/perception";
import type { LivePlanStep, ClarificationPrompt, ApprovalPrompt } from "@/types/run";

interface LiveRunCanvasProps {
  runId: string;
}

export function LiveRunCanvas({ runId }: LiveRunCanvasProps) {
  const { data: run, refetch: refetchRun, isLoading } = useRunDetail(runId);

  // Live state from SSE stream
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [planSteps, setPlanSteps] = useState<LivePlanStep[]>([]);
  const [activeStepIndex, setActiveStepIndex] = useState<number | null>(null);
  const [clarification, setClarification] = useState<ClarificationPrompt | null>(null);
  const [clarifyAnswer, setClarifyAnswer] = useState("");
  const [approval, setApproval] = useState<ApprovalPrompt | null>(null);
  const [isSubmittingControl, setIsSubmittingControl] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);
  const [streamStatus, setStreamStatus] = useState<"connecting" | "connected" | "reconnecting" | "unavailable">("connecting");
  const [streamError, setStreamError] = useState<string | null>(null);
  const [preconditionFailureNotice, setPreconditionFailureNotice] = useState<string | null>(null);

  const currentStatus = liveStatus || run?.status || "queued";
  const isLive = currentStatus === "running" || currentStatus === "queued" || currentStatus === "paused" || currentStatus === "awaiting_user_input";
  const isPaused = currentStatus === "paused";

  const { data: evidence, refetch: refetchEvidence } = useRunPerception(runId, isLive);

  // Stepper state
  const [frameIdx, setFrameIdx] = useState<number | null>(null);
  const frames = evidence ? evidenceToFrames(evidence) : [];
  const total = frames.length;

  useEffect(() => {
    if (isLive && total > 0) {
      setFrameIdx((idx) => (idx === null || idx >= total - 1 ? total - 1 : idx));
    }
  }, [isLive, total]);

  // Connect to the short-lived, run-scoped SSE ticket. Do not put a full JWT
  // into the URL: query strings can be retained in proxy and access logs.
  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let connectionInFlight = false;
    let reconnectAttempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleReconnect = (message: string) => {
      if (cancelled || reconnectTimer) return;
      if (es) {
        es.close();
        es = null;
      }
      setStreamStatus("reconnecting");
      setStreamError((current) => current || message);
      const delayMs = Math.min(30_000, 1_000 * 2 ** Math.min(reconnectAttempts, 5));
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void connectSSE();
      }, delayMs);
    };

    async function connectSSE() {
      if (cancelled || connectionInFlight) return;
      connectionInFlight = true;
      setStreamStatus(reconnectAttempts > 0 ? "reconnecting" : "connecting");

      if (!getToken()) {
        setStreamStatus("unavailable");
        setStreamError("Your session is unavailable. Sign in again to receive live events.");
        connectionInFlight = false;
        return;
      }

      let ticket: string;
      try {
        const res = await api.getStreamTicket(runId);
        if (!res?.ticket) throw new Error("The server did not return a live-stream ticket.");
        ticket = res.ticket;
      } catch (error) {
        connectionInFlight = false;
        if (!cancelled) {
          const statusCode = (error as { response?: { status?: number } })?.response?.status;
          const message = error instanceof Error
            ? `Live events could not be authorized: ${error.message}`
            : "Live events could not be authorized. Run status will continue to refresh.";
          setStreamError(message);
          if (statusCode === 401 || statusCode === 403 || !getToken()) {
            setStreamStatus("unavailable");
          } else {
            scheduleReconnect("Live ticket request failed; retrying with a fresh ticket.");
          }
        }
        return;
      }

      if (cancelled) {
        connectionInFlight = false;
        return;
      }

      const sseUrl = resolveApiUrl(
        `/api/v1/runs/${runId}/events?ticket=${encodeURIComponent(ticket)}`
      );
      const eventSource = new EventSource(sseUrl);
      es = eventSource;
      connectionInFlight = false;

      eventSource.onopen = () => {
        if (!cancelled) {
          setStreamStatus("connected");
          setStreamError(null);
          reconnectAttempts = 0;
        }
      };

      eventSource.addEventListener("connected", () => {
        if (!cancelled) {
          setStreamStatus("connected");
          setStreamError(null);
          reconnectAttempts = 0;
        }
      });

      eventSource.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);
          const eventType = raw?.event_type || raw?.type;
          if (!eventType) return;

          const p = raw.payload && typeof raw.payload === "object" ? { ...raw, ...raw.payload } : raw;

          switch (eventType) {
            case "plan_created":
              if (p.plan?.steps) {
                setPlanSteps(p.plan.steps);
              } else if (Array.isArray(p.steps)) {
                setPlanSteps(p.steps);
              }
              break;
            case "step_started":
              if (p.step_index !== undefined) {
                setActiveStepIndex(p.step_index);
                setLiveStatus("running");
                setPlanSteps((prev) =>
                  prev.map((s) => (s.step_index === p.step_index ? { ...s, status: "in_progress" } : s))
                );
                refetchEvidence();
              }
              break;
            case "step_finished":
              if (p.step_index !== undefined) {
                setPlanSteps((prev) =>
                  prev.map((s) =>
                    s.step_index === p.step_index
                      ? {
                          ...s,
                          status: p.status === "failed" ? "failed" : "success",
                          observed_values: p.observed_values || s.observed_values,
                          expected_values: p.expected_values || s.expected_values,
                          error: p.status === "failed" ? p.actual_result || "Step failed" : null,
                        }
                      : s
                  )
                );
                refetchEvidence();
              }
              break;
            case "precondition_check_failed":
              setLiveStatus("precondition_failed");
              setPreconditionFailureNotice(
                p.reason || "Precondition verification failed: record number or field state did not match expected value."
              );
              refetchRun();
              break;
            case "clarification_requested":
              setLiveStatus("awaiting_user_input");
              setClarification(
                p.clarification || {
                  request_id: p.request_id || "req-1",
                  question: p.question || "Clarification needed",
                  options: p.options || [],
                }
              );
              break;
            case "approval_prompt":
              setLiveStatus("awaiting_user_input");
              setApproval(
                p.approval || {
                  prompt_id: p.prompt_id || "prop-1",
                  step_index: p.step_index ?? 0,
                  description: p.action || p.description || "Approval requested for high risk action",
                  risk_score: p.risk_score ?? 8,
                }
              );
              break;
            case "run_paused":
              setLiveStatus("paused");
              break;
            case "run_resumed":
              setLiveStatus("running");
              break;
            case "run_cancelled":
              setLiveStatus("cancelled");
              refetchRun();
              break;
            case "run_finished":
              setLiveStatus(p.status || "completed");
              refetchRun();
              refetchEvidence();
              break;
            case "run_failed":
              setLiveStatus("failed");
              refetchRun();
              break;
            default:
              break;
          }
        } catch {
          // Ignore malformed event data; polling keeps the run summary current.
        }
      };

      eventSource.addEventListener("state_snapshot", (event: MessageEvent) => {
        try {
          const state = JSON.parse(event.data);
          if (state.status) setLiveStatus(state.status);
          if (state.current_step_index !== undefined) setActiveStepIndex(state.current_step_index);
        } catch {
          // Ignore malformed snapshot data.
        }
      });

      // The server can send an explicit named error event; EventSource also uses
      // onerror for transport failures. Keep those states distinguishable.
      eventSource.addEventListener("error", (event: Event) => {
        const messageEvent = event as MessageEvent<string>;
        if (messageEvent.data) {
          try {
            const payload = JSON.parse(messageEvent.data);
            const message = payload?.payload?.error || payload?.error;
            if (message) setStreamError(`Live event server reported an error: ${String(message)}`);
          } catch {
            setStreamError("Live event server reported an unreadable error.");
          }
        }
      });

      eventSource.onerror = () => {
        if (cancelled || es !== eventSource) return;
        scheduleReconnect(
          "Live event stream disconnected or its short-lived ticket expired; requesting a fresh ticket."
        );
      };
    }

    void connectSSE();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (es) es.close();
    };
  }, [runId, refetchRun, refetchEvidence]);

  const currentFrame: PerceptionFrame | undefined =
    total > 0 ? frames[frameIdx ?? total - 1] : undefined;

  const prevFrame = () => setFrameIdx((i) => Math.max(0, (i ?? total - 1) - 1));
  const nextFrame = () => setFrameIdx((i) => Math.min(total - 1, (i ?? total - 1) + 1));

  // Interactive control actions — surface failures instead of silently rejecting.
  const handlePause = async () => {
    setIsSubmittingControl(true);
    setControlError(null);
    try {
      await api.pauseRun(runId);
      setLiveStatus("paused");
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "Unable to pause the run.");
      void refetchRun();
    } finally {
      setIsSubmittingControl(false);
    }
  };

  const handleResume = async () => {
    setIsSubmittingControl(true);
    setControlError(null);
    try {
      await api.resumeRun(runId);
      setLiveStatus("running");
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "Unable to resume the run.");
      void refetchRun();
    } finally {
      setIsSubmittingControl(false);
    }
  };

  const handleCancel = async () => {
    if (!confirm("Are you sure you want to cancel this agent run?")) return;
    setIsSubmittingControl(true);
    setControlError(null);
    try {
      await api.cancelRun(runId);
      setLiveStatus("cancelled");
      void refetchRun();
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "Unable to cancel the run.");
      void refetchRun();
    } finally {
      setIsSubmittingControl(false);
    }
  };

  const handleSendClarification = async () => {
    if (!clarification || !clarifyAnswer.trim()) return;
    setIsSubmittingControl(true);
    setControlError(null);
    try {
      await api.clarifyRun(runId, clarification.request_id, clarifyAnswer.trim());
      setClarification(null);
      setClarifyAnswer("");
      setLiveStatus("running");
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "Unable to submit clarification.");
      void refetchRun();
    } finally {
      setIsSubmittingControl(false);
    }
  };

  const handleApprovalDecision = async (approved: boolean) => {
    if (!approval) return;
    setIsSubmittingControl(true);
    setControlError(null);
    try {
      await api.approveRun(runId, approval.prompt_id, approved);
      setApproval(null);
      setLiveStatus("running");
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "Unable to submit approval decision.");
      void refetchRun();
    } finally {
      setIsSubmittingControl(false);
    }
  };

  return (
    <div className="fixed inset-0 flex flex-col bg-graphite-950 font-sans">
      {/* Top Chrome / Interactive Desktop Bar */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-graphite-600 bg-graphite-900/95 px-4 backdrop-blur">
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
            <span
              className="rounded border border-graphite-700 bg-graphite-950/60 px-1.5 py-0.5 font-mono text-xs text-ink-400"
              title={run.id}
            >
              {run.id.slice(0, 8)}…
            </span>
          ) : null}
        </div>

        {/* Live Controls Toolbar */}
        <div className="flex items-center gap-3">
          {isLive && (
            <div className="flex items-center gap-2 mr-2 border-r border-graphite-600 pr-3">
              {isPaused ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleResume}
                  disabled={isSubmittingControl}
                  className="h-7 text-xs border-signal-teal/40 text-signal-teal hover:bg-signal-teal/10"
                >
                  <Play size={12} className="mr-1 fill-current" />
                  Resume
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePause}
                  disabled={isSubmittingControl}
                  className="h-7 text-xs border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
                >
                  <Pause size={12} className="mr-1 fill-current" />
                  Pause
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
                disabled={isSubmittingControl}
                className="h-7 text-xs border-red-500/40 text-red-400 hover:bg-red-500/10"
              >
                <Square size={12} className="mr-1 fill-current" />
                Cancel
              </Button>
            </div>
          )}

          <RunStatusBadge status={currentStatus as any} withDot />

          <Link to="/runs" aria-label="Close run view">
            <Button variant="ghost" size="icon">
              <X size={16} />
            </Button>
          </Link>
        </div>
      </div>

      {controlError && (
        <div role="alert" className="flex items-start justify-between gap-3 border-b border-red-500/40 bg-red-950/30 px-6 py-3 text-sm text-red-200">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 shrink-0 text-red-400" size={16} aria-hidden="true" />
            <p>{controlError}</p>
          </div>
          <button
            type="button"
            className="text-xs text-red-200 underline hover:text-white"
            onClick={() => setControlError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Clarification Gate Modal Banner */}
      {clarification && (
        <div className="flex items-center justify-between gap-4 border-b border-signal-teal/30 bg-signal-teal/10 px-6 py-3 backdrop-blur-sm z-20">
          <div className="flex items-start gap-3">
            <HelpCircle className="mt-0.5 shrink-0 text-signal-teal" size={18} />
            <div>
              <p className="font-mono text-xs font-semibold uppercase tracking-wider text-signal-teal">Agent Needs Clarification</p>
              <p className="text-sm font-medium text-ink-100">{clarification.question}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <input
              type="text"
              value={clarifyAnswer}
              onChange={(e) => setClarifyAnswer(e.target.value)}
              placeholder="Type clarification..."
              className="w-64 rounded-md border border-graphite-600 bg-graphite-950/80 px-3 py-1.5 text-xs text-ink-100 placeholder-ink-600 focus:outline-none focus:ring-1 focus:ring-signal-teal"
              onKeyDown={(e) => e.key === "Enter" && handleSendClarification()}
            />
            <Button
              size="sm"
              onClick={handleSendClarification}
              disabled={isSubmittingControl || !clarifyAnswer.trim()}
              className="h-8 bg-signal-teal text-xs text-graphite-950 hover:bg-signal-teal/90"
            >
              Reply
            </Button>
          </div>
        </div>
      )}

      {/* High-Risk Approval Gate Modal Banner */}
      {approval && (
        <div className="flex items-center justify-between gap-4 border-b border-amber-500/40 bg-amber-500/10 px-6 py-3 backdrop-blur-sm z-20">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 shrink-0 text-amber-400" size={20} />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-mono text-xs font-semibold uppercase tracking-wider text-amber-400">High Risk Action Approval Required</p>
                <span className="rounded-md border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 font-mono text-2xs font-bold text-amber-300">
                  Risk Score {approval.risk_score}/10
                </span>
              </div>
              <p className="text-sm text-ink-100">{approval.description}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleApprovalDecision(false)}
              disabled={isSubmittingControl}
              className="border-status-failed/40 text-sm text-status-failed hover:bg-status-failed/10"
            >
              Reject
            </Button>
            <Button
              size="sm"
              onClick={() => handleApprovalDecision(true)}
              disabled={isSubmittingControl}
              className="bg-amber-500 font-medium text-xs text-graphite-950 hover:bg-amber-400"
            >
              Approve & Execute
            </Button>
          </div>
        </div>
      )}

      {/* Precondition Failure Alert Banner */}
      {preconditionFailureNotice && (
        <div className="flex items-center gap-3 border-b border-amber-500/40 bg-amber-500/10 px-6 py-3 backdrop-blur-sm z-20">
          <AlertTriangle className="shrink-0 text-amber-400" size={18} />
          <div>
            <p className="font-mono text-xs font-semibold uppercase tracking-wider text-amber-400">
              Precondition Gate Halt — 0 Application Defects
            </p>
            <p className="text-xs text-ink-100">{preconditionFailureNotice}</p>
          </div>
        </div>
      )}

      {/* Main workspace: Perception Canvas (left 65%) + Canonical Execution Plan (right 35%) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Perception Overlay */}
        <div className="relative flex flex-1 flex-col overflow-hidden bg-graphite-950">
          <PerceptionOverlay frame={currentFrame} isLive={isLive} />

          {/* Frame stepper */}
          {total > 0 && (
            <div className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-3 rounded border border-graphite-600 bg-graphite-800/90 px-3 py-1.5 shadow-lg backdrop-blur">
              <button
                onClick={prevFrame}
                disabled={(frameIdx ?? total - 1) <= 0}
                className="text-ink-400 hover:text-ink-100 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal rounded"
                aria-label="Previous frame"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="font-mono text-xs text-ink-400">
                Frame {(frameIdx ?? total - 1) + 1} / {total}
              </span>
              <button
                onClick={nextFrame}
                disabled={(frameIdx ?? total - 1) >= total - 1}
                className="text-ink-400 hover:text-ink-100 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal rounded"
                aria-label="Next frame"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>

        {/* Right Sidebar: Goal, Live Plan Stepper & Metadata */}
        <aside className="flex w-96 shrink-0 flex-col overflow-y-auto border-l border-graphite-600 bg-graphite-900/60 backdrop-blur-sm">
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
                <p className="text-sm text-ink-100 font-medium leading-snug">{run.goal}</p>
              </div>

              {/* Canonical Execution Plan Live Stepper */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="data-label">Execution Plan</p>
                  {planSteps.length > 0 && (
                    <span className="font-mono text-2xs text-ink-400">
                      {planSteps.filter((s) => s.status === "success").length}/{planSteps.length} done
                    </span>
                  )}
                </div>

                {planSteps.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    {planSteps.map((step) => {
                      const isActive = activeStepIndex === step.step_index;
                      return (
                        <div
                          key={step.step_index}
                          className={`rounded border p-2.5 transition-colors ${
                            isActive
                              ? "border-signal-teal/60 bg-signal-teal/5"
                              : step.status === "failed"
                              ? "border-red-500/40 bg-red-950/40"
                              : step.status === "skipped"
                              ? "border-graphite-600 bg-graphite-900/40 opacity-70"
                              : "border-graphite-600/80 bg-graphite-900/60"
                          }`}
                        >
                          <div className="flex items-start gap-2.5">
                            <span className="mt-0.5 shrink-0">
                              {step.status === "in_progress" ? (
                                <Loader2 size={15} className="animate-spin text-signal-teal" />
                              ) : step.status === "success" ? (
                                <CheckCircle2 size={15} className="text-signal-teal" />
                              ) : step.status === "failed" ? (
                                <XCircle size={15} className="text-red-400" />
                              ) : step.status === "skipped" ? (
                                <span className="inline-block w-3.5 h-0.5 bg-ink-600 my-1.5" />
                              ) : step.status === "blocked" ? (
                                <AlertCircle size={15} className="text-amber-400" />
                              ) : (
                                <span className="inline-block w-2.5 h-2.5 rounded-full border border-ink-600 my-1" />
                              )}
                            </span>

                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-1">
                                <span className="font-mono text-2xs font-semibold text-ink-400">
                                  Step {step.step_index + 1}
                                </span>
                                <span
                                  className={`rounded px-1.5 py-0.5 font-mono text-3xs uppercase ${
                                    step.status === "success"
                                      ? "bg-signal-teal/15 text-signal-teal"
                                      : step.status === "in_progress"
                                      ? "animate-pulse bg-signal-teal/20 text-signal-teal"
                                      : step.status === "failed"
                                      ? "bg-red-500/20 text-red-400"
                                      : step.status === "skipped"
                                      ? "bg-graphite-800 text-ink-600"
                                      : "text-ink-400"
                                  }`}
                                >
                                  {step.status}
                                </span>
                              </div>
                              <p className="mt-0.5 text-xs leading-tight text-ink-200">{step.description}</p>

                              {/* Observed vs Expected Diff Card */}
                              {(step.observed_values || step.expected_values) && (
                                <div className="mt-2 rounded border border-graphite-700 bg-graphite-950 p-2 font-mono text-2xs">
                                  {step.expected_values && (
                                    <p className="text-ink-400">
                                      <span className="text-signal-teal">Expected:</span>{" "}
                                      {JSON.stringify(step.expected_values)}
                                    </p>
                                  )}
                                  {step.observed_values && (
                                    <p className="mt-0.5 text-ink-400">
                                      <span className="text-amber-400">Observed:</span>{" "}
                                      {JSON.stringify(step.observed_values)}
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded border border-dashed border-graphite-600 p-3 text-center">
                    <p className="font-mono text-2xs text-ink-600">
                      {isLive ? "Synthesizing execution plan..." : "No steps recorded."}
                    </p>
                  </div>
                )}
              </div>

              {/* Metadata */}
              <div className="flex flex-col gap-2.5 border-t border-graphite-600 pt-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-400">Started</span>
                  <span className="font-mono text-ink-200">{formatDateTime(run.start_time)}</span>
                </div>
                {run.duration_seconds !== null && (
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-ink-400">Duration</span>
                    <span className="font-mono text-ink-200">{formatDuration(run.duration_seconds)}</span>
                  </div>
                )}
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-400">Defects Found</span>
                  <span
                    className={`font-mono font-medium ${
                      run.defect_count > 0 ? "text-amber-400" : "text-ink-200"
                    }`}
                  >
                    {run.defect_count}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-400">API persistence</span>
                  <span className="font-mono text-ink-200">{run.api_verification_status || "not attempted"}</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-400">Cleanup</span>
                  <span className={`font-mono ${run.cleanup_status === "cleanup_failed" ? "text-red-400" : "text-ink-200"}`}>
                    {run.cleanup_status || "not run"}
                  </span>
                </div>
                {run.cleanup_details && (
                  <p className="rounded border border-red-500/30 bg-red-950/20 p-2 text-2xs text-red-300">
                    {run.cleanup_details}
                  </p>
                )}
              </div>

              {/* Live event transport status; run details continue polling independently. */}
              {isLive && (
                <div className="pt-1" role="status" aria-live="polite">
                  <div className={`flex items-center gap-2 text-2xs ${
                    streamStatus === "connected" ? "text-signal-teal" : "text-amber-300"
                  }`}>
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        streamStatus === "connected" ? "animate-pulse bg-signal-teal" : "bg-amber-300"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="font-mono">
                      {streamStatus === "connected"
                        ? "Real-time event stream connected"
                        : streamStatus === "connecting"
                        ? "Connecting to live event stream…"
                        : streamStatus === "reconnecting"
                        ? "Live event stream disconnected; reconnecting…"
                        : "Live event stream unavailable; run status is still polling"}
                    </span>
                  </div>
                  {streamError && streamStatus !== "connected" && (
                    <p className="mt-1 text-2xs text-amber-200">{streamError}</p>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
