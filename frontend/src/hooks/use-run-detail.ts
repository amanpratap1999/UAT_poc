import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { RunDetail } from "@/types/run";

export function runDetailQueryKey(runId: string) {
  return ["runs", runId] as const;
}

export function useRunDetail(runId: string | undefined) {
  return useQuery({
    queryKey: runDetailQueryKey(runId ?? ""),
    queryFn: ({ signal }) => api.get<RunDetail>(`/api/v1/runs/${runId}`, signal),
    enabled: !!runId,
    staleTime: 5_000,
    refetchInterval: (query) => {
      // Poll every 3s while run is live; stop once terminal
      const data = query.state.data;
      if (!data) return 3_000;
      const liveStatuses = ["queued", "running"];
      return liveStatuses.includes(data.status) ? 3_000 : false;
    },
  });
}
