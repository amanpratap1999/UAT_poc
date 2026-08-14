import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { RunDetail } from "@/types/run";
import { runDetailQueryKey } from "./use-run-detail";

const LIVE_STATUSES = new Set(["queued", "running"]);
const POLL_INTERVAL_MS = 3_000;

/**
 * RunEventSource — the abstraction layer between the UI and the real-time transport.
 *
 * Current implementation: REST polling (3s interval while run is live).
 * Future implementation: WebSocket — replace the poll() method with connect()
 * without changing any consumer code.
 *
 * Usage: useRunMonitor(runId) returns the latest RunDetail from the query cache,
 * automatically stopping when the run reaches a terminal state.
 */
export function useRunMonitor(runId: string | undefined, onUpdate?: (run: RunDetail) => void) {
  const queryClient = useQueryClient();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isLiveRef = useRef(false);

  const poll = useCallback(async () => {
    if (!runId) return;
    try {
      const run = await api.get<RunDetail>(`/api/v1/runs/${runId}`);
      queryClient.setQueryData(runDetailQueryKey(runId), run);
      onUpdate?.(run);

      if (!LIVE_STATUSES.has(run.status)) {
        // Run reached terminal state — stop polling
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
        isLiveRef.current = false;
      }
    } catch {
      // Network error — keep polling (run may still be live)
    }
  }, [runId, queryClient, onUpdate]);

  useEffect(() => {
    if (!runId) return;

    // Check initial state
    const cached = queryClient.getQueryData<RunDetail>(runDetailQueryKey(runId));
    if (cached && !LIVE_STATUSES.has(cached.status)) {
      // Already terminal — don't start polling
      isLiveRef.current = false;
      return;
    }

    isLiveRef.current = true;

    // Start polling
    void poll();
    intervalRef.current = setInterval(() => void poll(), POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [runId, poll, queryClient]);

  return {
    isLive: isLiveRef.current,
    /**
     * Future hook point: call this to upgrade from polling to WebSocket.
     * When a real WebSocket endpoint exists, replace poll() with this.
     */
    _wsConnectStub: () => {
      console.warn(
        "[RunEventSource] WebSocket transport not yet available. Using REST polling. " +
          "Implement ws:// endpoint at /ws/runs/{run_id} and wire it here."
      );
    },
  };
}
