import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, AlertCircle, RefreshCw } from "lucide-react";
import { api } from "@/lib/api-client";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils";

/** GET /api/v1/knowledge-model/rules */
interface KnowledgeRule {
  rule_id: string;
  table: string;
  name: string;
  type: string; // business_rule | ui_policy | client_script | dictionary
  description: string;
  is_active: boolean;
  details: Record<string, unknown>;
}

interface KnowledgeModelRulesResponse {
  total: number;
  tables: string[];
  rules: KnowledgeRule[];
}

interface KnowledgeTable {
  name: string;
  discovery_status: string;
  discovery_error?: string | null;
  source_status: Record<string, string>;
  field_count: number;
}

interface KnowledgeTablesResponse {
  tables: KnowledgeTable[];
}

/** GET /api/v1/knowledge-model/drift */
interface KnowledgeDriftResponse {
  has_drift: boolean;
  last_checked: string;
  drifted_tables: string[];
  model_version: string;
}

const RULE_TYPE_BADGE: Record<string, "app-bug" | "business-rule" | "config-diff" | "expected-custom" | "default"> = {
  business_rule: "app-bug",
  ui_policy: "business-rule",
  client_script: "config-diff",
  dictionary: "expected-custom",
};

export default function KnowledgeModel() {
  const [tableFilter, setTableFilter] = useState<string | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["knowledge-model", "rules"],
    queryFn: ({ signal }) =>
      api.get<KnowledgeModelRulesResponse>("/api/v1/knowledge-model/rules", signal),
    staleTime: 60_000,
  });

  const driftQuery = useQuery({
    queryKey: ["knowledge-model", "drift"],
    queryFn: ({ signal }) =>
      api.get<KnowledgeDriftResponse>("/api/v1/knowledge-model/drift", signal),
    staleTime: 60_000,
  });

  const tablesQuery = useQuery({
    queryKey: ["knowledge-model", "tables"],
    queryFn: ({ signal }) =>
      api.get<KnowledgeTablesResponse>("/api/v1/knowledge-model/tables", signal),
    staleTime: 60_000,
  });

  const rules = rulesQuery.data?.rules ?? [];
  const tables = rulesQuery.data?.tables ?? [];
  const filtered = tableFilter
    ? rules.filter((r) => r.table.toLowerCase() === tableFilter.toLowerCase())
    : rules;

  const rulesByTable = new Map<string, number>();
  for (const r of rules) {
    rulesByTable.set(r.table, (rulesByTable.get(r.table) ?? 0) + 1);
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Knowledge Model</h1>
          <p className="page-subtitle">
            Deterministic rules and discovered customizations for your ServiceNow instance
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Refresh knowledge model"
            isLoading={rulesQuery.isFetching || driftQuery.isFetching}
            onClick={() => {
              void rulesQuery.refetch();
              void driftQuery.refetch();
              void tablesQuery.refetch();
          }}
        >
          <RefreshCw size={16} />
        </Button>
      </div>

      {/* Errors */}
      {rulesQuery.error && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-status-failed/30 bg-status-failed/5 p-4 text-sm text-status-failed"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Unable to load knowledge model</p>
            <p className="mt-1 text-xs opacity-80">
              {rulesQuery.error instanceof Error
                ? rulesQuery.error.message
                : "Check that the backend is running."}
            </p>
          </div>
        </div>
      )}

      {/* Drift status */}
      <Card>
        <CardHeader>
          <CardTitle>Drift Detection</CardTitle>
        </CardHeader>
        <CardContent>
          {driftQuery.isLoading ? (
            <Skeleton className="h-5 w-64" />
          ) : driftQuery.data ? (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <div className="flex items-center gap-2">
                <span className="data-label">Status</span>
                <Badge variant={driftQuery.data.has_drift ? "blocked" : "completed"}>
                  {driftQuery.data.has_drift ? "Drift detected" : "No drift"}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="data-label">Last checked</span>
                <span className="font-mono text-xs text-body">
                  {formatDateTime(driftQuery.data.last_checked)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="data-label">Model version</span>
                <span className="font-mono text-xs text-body">
                  {driftQuery.data.model_version}
                </span>
              </div>
              {driftQuery.data.drifted_tables.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="data-label">Drifted tables</span>
                  <span className="font-mono text-xs text-status-blocked">
                    {driftQuery.data.drifted_tables.join(", ")}
                  </span>
                </div>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Table summary cards */}
      {rulesQuery.isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-4 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : tables.length === 0 ? (
        <div className="surface-card flex flex-col items-center gap-3 py-12 text-center">
          <BookOpen size={24} className="text-faint" aria-hidden="true" />
          <p className="text-sm text-ink">The Customer Knowledge Model is empty.</p>
          <p className="max-w-md text-xs leading-relaxed text-body">
            Rules appear here after the Customer Discovery Agent runs against your
            ServiceNow instance and populates the knowledge model (dictionary
            entries, UI policies, business rules).
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {tables.map((table) => (
            <Card
              key={table}
              className={`group transition-all duration-200 hover:-translate-y-0.5 hover:shadow-raise ${
                tableFilter === table ? "ring-2 ring-accent/30" : ""
              }`}
            >
              <CardHeader>
                <CardTitle className="flex items-center gap-2 normal-case tracking-normal text-ink">
                  <BookOpen size={13} className="text-muted" aria-hidden="true" />
                  {table}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col gap-3">
                  {(() => {
                    const metadata = tablesQuery.data?.tables.find((item) => item.name === table);
                    const status = metadata?.discovery_status ?? "UNKNOWN";
                    const variant = status === "AVAILABLE" ? "completed" : status === "FAILED" ? "failed" : "blocked";
                    return (
                      <div className="flex items-center justify-between gap-2">
                        <span className="data-label">Discovery</span>
                        <Badge variant={variant}>{status.toLowerCase()}</Badge>
                      </div>
                    );
                  })()}
                  <div className="flex items-center justify-between">
                    <span className="data-label">Discovered rules</span>
                    <span className="font-mono text-lg font-medium text-ink">
                      {rulesByTable.get(table) ?? 0}
                    </span>
                  </div>
                  <Button
                    variant={tableFilter === table ? "primary" : "outline"}
                    size="sm"
                    onClick={() =>
                      setTableFilter(tableFilter === table ? null : table)
                    }
                    className="w-fit"
                  >
                    {tableFilter === table ? "Clear filter" : "View rules"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Rules table */}
      {filtered.length > 0 && (
        <div className="surface-card overflow-hidden p-0">
          <div className="border-b border-line px-4 py-3">
            <p className="font-mono text-xs text-body">
              {filtered.length} rule{filtered.length === 1 ? "" : "s"}
              {tableFilter ? ` — table: ${tableFilter}` : " — all tables"}
            </p>
          </div>
          <ul role="list" className="divide-y divide-line">
            {filtered.map((rule) => (
              <li
                key={rule.rule_id}
                className="flex flex-col gap-1 px-4 py-3 transition-colors hover:bg-accent-soft/50"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-ink">{rule.name}</span>
                  <Badge variant={RULE_TYPE_BADGE[rule.type] ?? "default"}>
                    {rule.type.replace("_", " ")}
                  </Badge>
                </div>
                <p className="text-xs text-body">{rule.description}</p>
                <p className="font-mono text-2xs text-faint">
                  {rule.rule_id}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
