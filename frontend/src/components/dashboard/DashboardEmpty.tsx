import { Link } from "react-router-dom";
import { PlayCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function DashboardEmpty() {
  return (
    <div className="surface-card flex flex-col items-center gap-5 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-line bg-canvas text-faint">
        <PlayCircle size={24} aria-hidden="true" />
      </div>
      <div className="max-w-sm">
        <h2 className="font-display text-lg font-semibold text-ink">
          No runs yet
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-body">
          Start your first QA run to begin collecting metrics and findings. The agent will
          autonomously navigate your ServiceNow instance and report what it finds.
        </p>
      </div>
      <Link to="/runs">
        <Button variant="primary" size="md" className="gap-2">
          Start your first run
          <ArrowRight size={16} aria-hidden="true" />
        </Button>
      </Link>
    </div>
  );
}
