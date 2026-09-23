import { useState } from "react";
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
  const [personas, setPersonas] = useState("itil,approver");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<any>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const personaList = personas.split(",").map((item) => item.trim()).filter(Boolean);

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
    setBusy(true);
    setMessage("");
    try {
      const batches = (await api.importTestCases(selectedFile, { personas: personaList })) as ImportBatch[];
      const imported = batches.flatMap((batch) => batch.test_cases ?? []);
      const importedRuns = batches.flatMap((batch) => (batch.runs ?? []).flatMap((run) => run.run_id ? [run.run_id] : []));
      setCases(imported);
      setRunIds(importedRuns);
      setMessage(`${imported.length} test case(s) imported.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function sweep(testCaseId: string) {
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
    setBusy(true);
    try {
      setComparison(await api.comparePersonas(testCaseId, personaList));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Comparison failed.");
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
            <input type="file" accept=".xlsx" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} className="block w-full rounded-md border border-line bg-card p-2 text-sm text-body" />
            <Button variant="secondary" onClick={() => void importWorkbook()} disabled={!selectedFile} isLoading={busy} className="gap-2"><Upload size={15} /> Import XLSX</Button>
          </CardContent>
        </Card>
      </div>

      {message && <p role="status" className="rounded-md border border-line bg-card px-4 py-3 text-sm text-body">{message}</p>}

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
                    <Button size="sm" variant="secondary" onClick={() => void sweep(testCase.id)} disabled={busy} className="gap-1"><Play size={13} /> Sweep personas</Button>
                    <Button size="sm" variant="outline" onClick={() => void compare(testCase.id)} disabled={busy} className="gap-1"><GitCompare size={13} /> Compare</Button>
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
