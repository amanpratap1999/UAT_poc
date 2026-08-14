import { BookOpen, AlertCircle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

/**
 * Knowledge Model page — Phase 4.
 *
 * BLOCKED: The backend does not currently expose a queryable Knowledge Model HTTP API.
 * The CustomerKnowledgeModel class is an in-memory domain object used internally.
 *
 * This page implements the UI shell and domain abstraction.
 * It will render real data once the backend exposes:
 *   GET /api/v1/knowledge-model/rules
 *   GET /api/v1/knowledge-model/rules/{rule_id}
 *   GET /api/v1/knowledge-model/drift
 */
export default function KnowledgeModel() {
  // Placeholder data structure — matches what the backend CustomerKnowledgeModel exposes
  const MOCK_TABLES = [
    { name: "incident", fields: 12, rules: 5, lastVerified: null },
    { name: "problem", fields: 8, rules: 3, lastVerified: null },
    { name: "change_request", fields: 15, rules: 7, lastVerified: null },
  ];

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
          Knowledge Model
        </h1>
        <p className="mt-1 text-sm text-ink-400">
          Deterministic rules and discovered customizations for your ServiceNow instance
        </p>
      </div>

      {/* BLOCKED notice */}
      <div className="flex items-start gap-3 rounded border border-amber-500/30 bg-amber-500/10 p-4">
        <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
        <div>
          <p className="text-sm font-medium text-ink-100">
            Knowledge Model API not yet available
          </p>
          <p className="mt-1 text-xs text-ink-400">
            The backend <code className="font-mono">CustomerKnowledgeModel</code> is an
            in-memory domain object. A queryable REST API (
            <code className="font-mono">GET /api/v1/knowledge-model/rules</code>) does not
            yet exist. This explorer will display live data once that endpoint is implemented.
          </p>
          <p className="mt-2 text-xs text-ink-400">
            Required backend additions:
          </p>
          <ul className="mt-1 list-inside list-disc text-xs text-ink-600 font-mono">
            <li>GET /api/v1/knowledge-model/rules</li>
            <li>GET /api/v1/knowledge-model/rules/{"{rule_id}"}</li>
            <li>GET /api/v1/knowledge-model/drift</li>
          </ul>
        </div>
      </div>

      {/* Table schema preview — shows structure without real data */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {MOCK_TABLES.map((table) => (
          <Card key={table.name}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpen size={12} aria-hidden="true" />
                {table.name}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="data-label">Fields</span>
                  <span className="font-mono text-xs text-ink-400">—</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="data-label">Rules</span>
                  <span className="font-mono text-xs text-ink-400">—</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="data-label">Last Verified</span>
                  <span className="font-mono text-xs text-ink-600">
                    Awaiting API
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Drift section placeholder */}
      <Card>
        <CardHeader>
          <CardTitle>Drift Detection</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-ink-400">
            Rules that have changed since last discovery will appear here. Requires{" "}
            <code className="font-mono text-xs">GET /api/v1/knowledge-model/drift</code>.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
