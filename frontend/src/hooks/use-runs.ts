import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { Run } from "@/types/run";

export const RUNS_QUERY_KEY = ["runs"] as const;

export function useRuns() {
  return useQuery({
    queryKey: RUNS_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Run[]>("/api/v1/runs", signal),
    staleTime: 30_000, // 30 seconds
    refetchInterval: 15_000, // Poll every 15s to catch status changes
  });
}
