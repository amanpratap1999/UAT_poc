import { useParams } from "react-router-dom";
import { LiveRunCanvas } from "@/components/runs/LiveRunCanvas";

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();

  if (!runId) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-sm text-ink-400">No run ID provided.</p>
      </div>
    );
  }

  return <LiveRunCanvas runId={runId} />;
}
