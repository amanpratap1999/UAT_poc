import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface ServiceNowPersonaOption {
  name: string;
  role: string | null;
}

export interface ServiceNowPersonasResponse {
  personas: ServiceNowPersonaOption[];
  active_persona: string | null;
  requires_persona: boolean;
}

export const SERVICENOW_PERSONAS_QUERY_KEY = ["servicenow-personas"] as const;

export function useServiceNowPersonas(enabled = true) {
  return useQuery({
    queryKey: SERVICENOW_PERSONAS_QUERY_KEY,
    queryFn: ({ signal }) =>
      api.get<ServiceNowPersonasResponse>("/api/v1/personas", signal),
    enabled,
    staleTime: 30_000,
  });
}
