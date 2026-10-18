import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useServiceNowPersonas } from "@/hooks/use-servicenow-personas";
import { Download, FileSpreadsheet, GitCompare, Play, Upload, WandSparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api-client";

type TestCase = {
  id: string;
  title: string;
  description?: string;
  steps?: Array<{ action_type?: string; target?: string; value?: string }>;
  expected_outcomes?: string[];
};

type ImportBatch = {
  test_cases?: TestCase[];
  runs?: Array<{ run_id?: string; status?: string; message?: string }>;
};

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function TestCases() {
  const [requirement, setRequirement] = useState("");
  const [personas, setPersonas] = useState("");
  const [selectedPersona, setSelectedPersona] = useState("");
  const [personaDefaultsApplied, setPersonaDefaultsApplied] = useState(false);
  const [lastExecutedRun, setLastExecutedRun] = useState<{ id: string; status: string } | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [executeOnImport, setExecuteOnImport] = useState(false);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<any>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const personaQuery = useServiceNowPersonas();
  const personaInfo = personaQuery.data;
  const personaList = personas.split(",").map((item) => item.trim()).filter(Boolean);
  const personaReady = Boolean(
    personaInfo &&
    !personaQuery.isLoading &&
    !personaQuery.isError &&
    (!personaInfo.requires_persona ||
      (Boolean(selectedPersona) && personaInfo.personas.some((item) => item.name === selectedPersona))),
  );

  useEffect(() => {
    if (!personaInfo || personaDefaultsApplied) return;
    const preferred = personaInfo.active_persona && personaInfo.personas.some((p) => p.name === personaInfo.active_persona)
      ? personaInfo.active_persona
      : personaInfo.personas[0]?.name ?? "";
    setSelectedPersona(preferred);
    setPersonas(personaInfo.personas.length
      ? (personaInfo.active_persona && personaInfo.personas.some((p) => p.name === personaInfo.active_persona)
          ? personaInfo.active_persona
          : personaInfo.personas.map((p) => p.name).join(", "))
      : "");
    setPersonaDefaultsApplied(true);
  }, [personaInfo, personaDefaultsApplied]);

  async function generate() {
    if (!requirement.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await api.generateTestCases({ requirement, table_name: "incident" });
      setCases(response.test_cases as TestCase[]);
      setMessage(`${response.count} test case(s) generated.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Generation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function importWorkbook() {
    if (!selectedFile) return;
    if (executeOnImport) {
      if (!personaInfo || personaQuery.isLoading || personaQuery.isError || !personaList.length) {
        setMessage("Select at least one configured ServiceNow persona before executing imported tests.");
        return;
      }
      const configured = new Set(personaInfo.personas.map((persona) => persona.name));
      if (personaList.some((persona) => !configured.has(persona))) {
        setMessage("Imported-test execution accepts configured personas only. Correct the persona list and retry.");
        return;
      }
    }
    setBusy(true);
    setMessage("");
    try {
      const batches = (await api.importTestCases(selectedFile, {
        personas: personaList,
        execute: executeOnImport,
      })) as ImportBatch[];
      const imported = batches.flatMap((batch) => batch.test_cases ?? []);
      const importedRuns = batches.flatMap((batch) =>
        (batch.runs ?? []).flatMap((run) => run.run_id ? [run.run_id] : []),
      );
      const firstRun = batches.flatMap((batch) => batch.runs ?? []).find((run) => Boolean(run.run_id));
      setCases(imported);
      setRunIds((current) => [...new Set([...current, ...importedRuns])]);
      setLastExecutedRun(firstRun?.run_id
        ? { id: firstRun.run_id, status: firstRun.status || "queued" }
        : null);
      setMessage(
        imported.length + " test case(s) imported" +
        (executeOnImport ? "; " + importedRuns.length + " run(s) created." : "."),
      );
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function sweep(testCaseId: string) {
    if (!personaList.length) {
      setMessage("Enter at least one configured persona before running a persona sweep.");
      return;
    }
    setBusy(true);
    try {
      const responses = await api.sweepTestCase(testCaseId, personaList);
      setRunIds((current) => [...current, ...responses.flatMap((run) => run.session_id ? [run.session_id] : [])]);
      setMessage(`Queued persona sweep for ${personaList.length} persona(s).`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Persona sweep failed.");
    } finally {
      setBusy(false);
    }
  }

  async function compare(testCaseId: string) {
    if (!personaList.length) {
      setMessage("Enter at least one configured persona before comparing personas.");
      return;
    }
    setBusy(true);
    try {
      setComparison(await api.comparePersonas(testCaseId, personaList));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Comparison failed.");
    } finally {
      setBusy(false);
    }
  }

  async function execute(testCaseId: string) {
    if (!personaReady || (personaInfo?.requires_persona && !selectedPersona)) {
      setMessage(
        personaQuery.isError
          ? "Could not load configured ServiceNow personas. Refresh and try again."
          : "A configured non-admin ServiceNow persona is required before executing a test case.",
      );
      return;
    }
    setBusy(true);
    setMessage("");
    setLastExecutedRun(null);
    try {
      const response = await api.executeTestCase(testCaseId, selectedPersona || undefined);
      setRunIds((current) => current.includes(response.session_id) ? current : [...current, response.session_id]);
      setLastExecutedRun({ id: response.session_id, status: response.status });
      setMessage(response.message || `Test case queued with status: ${response.status}`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Test case execution failed.");
    } finally {
      setBusy(false);
    }
  }

  async function exportResults() {
    if (!runIds.length) return;
    setBusy(true);
    try {
      const blob = await api.exportTestCaseResults(runIds);
      downloadBlob(blob, "uat-test-case-results.xlsx");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Export failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div>
        <h1 className="page-title">Test cases</h1>
        <p className="page-subtitle">Generate, import, execute, compare, and export UAT scenarios.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle><span className="flex items-center gap-2"><WandSparkles size={16} /> Generate from requirement</span></CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Input label="Requirement" value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="Incident must require resolution notes before closure" />
            <Button variant="primary" onClick={() => void generate()} disabled={!requirement.trim()} isLoading={busy}>Generate test cases</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle><span className="flex items-center gap-2"><FileSpreadsheet size={16} /> Import workbook</span></CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Input label="Personas" value={personas} onChange={(event) => setPersonas(event.target.value)} hint="Comma-separated personas used for sweeps and comparisons." />
            <label className="flex items-start gap-2 text-sm text-body">
              <input
                aria-label="Execute imported test cases after import"
                type="checkbox"
                checked={executeOnImport}
                onChange={(event) => setExecuteOnImport(event.target.checked)}
                disabled={busy}
                className="mt-1"
              />
              <span>
                <span className="block font-medium">Execute imported cases after import</span>
                <span className="block text-xs text-muted">
                  Queues each imported case for every listed configured persona. Leave unchecked to import only.
                </span>
              </span>
            </label>
            <input type="file" accept=".xlsx" aria-label="Test case workbook" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} className="block w-full rounded-md border border-line bg-card p-2 text-sm text-body" />
            <Button
              variant="secondary"
              onClick={() => void importWorkbook()}
              disabled={!selectedFile || busy || (executeOnImport && (
                !personaInfo || !personaList.length ||
                personaList.some((name) => !personaInfo.personas.some((persona) => persona.name === name))
              ))}
              isLoading={busy}
              className="gap-2"
            >
              <Upload size={15} /> Import XLSX
            </Button>
          </CardContent>
        </Card>
      </div>

      {lastExecutedRun && (
        <p className="rounded-md border border-line bg-card px-4 py-3 text-sm text-body">
          Run {lastExecutedRun.id} is {lastExecutedRun.status}.{" "}
          <Link className="font-medium text-accent underline" to={`/runs/${lastExecutedRun.id}`}>
            Open live run
          </Link>
        </p>
      )}
      {message && <p role="status" className="rounded-md border border-line bg-card px-4 py-3 text-sm text-body">{message}</p>}

      <Card>
        <CardContent className="flex flex-col gap-2 py-4">
          <label htmlFor="execute-persona" className="text-xs font-semibold text-body">
            Execute a test case as
          </label>
          {personaQuery.isLoading ? (
            <p role="status" className="text-xs text-muted">Loading configured ServiceNow personas…</p>
          ) : personaQuery.isError ? (
            <p role="alert" className="text-xs text-status-failed">
              Could not load configured ServiceNow personas. Refresh the page before executing tests.
            </p>
          ) : (
            <>
              <select
                id="execute-persona"
                value={selectedPersona}
                onChange={(event) => setSelectedPersona(event.target.value)}
                disabled={busy}
                className="w-full rounded-md border border-line bg-card px-3 py-2 text-sm text-body"
              >
                {!personaInfo?.requires_persona && <option value="">Use configured default</option>}
                {personaInfo?.personas.map((persona) => (
                  <option key={persona.name} value={persona.name}>
                    {persona.name}{persona.role ? ` — ${persona.role}` : ""}
                  </option>
                ))}
              </select>
              {personaInfo?.requires_persona && personaInfo.personas.length === 0 && (
                <p className="text-xs text-status-failed">
                  No personas are configured on the backend. Configure SERVICENOW_PERSONAS before starting UAT.
                </p>
              )}
            </>
          )}
          <Input label="Personas for sweep/comparison" value={personas} onChange={(event) => setPersonas(event.target.value)} hint="Comma-separated configured persona names." />
        </CardContent>
      </Card>

      <div className="flex items-center justify-between gap-3">
        <h2 className="section-title">Available test cases</h2>
        <Button variant="outline" onClick={() => void exportResults()} disabled={!runIds.length || busy} className="gap-2"><Download size={15} /> Export results</Button>
      </div>

      {cases.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-sm text-muted">Generate a case or import an XLSX workbook to begin.</CardContent></Card>
      ) : (
        <div className="flex flex-col gap-3">
          {cases.map((testCase) => (
            <Card key={testCase.id}>
              <CardContent className="flex flex-col gap-3 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-ink">{testCase.title}</h3>
                    <p className="mt-1 text-sm text-body">{testCase.description || "No description provided."}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="primary" onClick={() => void execute(testCase.id)} disabled={busy || !personaReady} className="gap-1"><Play size={13} /> Execute</Button>
                    <Button size="sm" variant="secondary" onClick={() => void sweep(testCase.id)} disabled={busy || !personaList.length} className="gap-1"><Play size={13} /> Sweep personas</Button>
                    <Button size="sm" variant="outline" onClick={() => void compare(testCase.id)} disabled={busy || !personaList.length} className="gap-1"><GitCompare size={13} /> Compare</Button>
                  </div>
                </div>
                <p className="font-mono text-xs text-muted">{testCase.steps?.length ?? 0} steps · {testCase.expected_outcomes?.length ?? 0} assertions · {testCase.id}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {comparison && (
        <Card>
          <CardHeader><CardTitle>Persona comparison</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm text-body">
            <p>Outcome: {comparison.same_outcome ? "same" : "different"}</p>
            {(comparison.access_differences ?? []).map((item: string) => <p key={item} className="text-status-warning">{item}</p>)}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
