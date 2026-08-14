import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-graphite-950 text-center">
      <p className="font-mono text-6xl font-light text-ink-600">404</p>
      <h1 className="font-display text-xl font-semibold text-ink-100">Page not found</h1>
      <p className="max-w-xs text-sm text-ink-400">
        The page you're looking for doesn't exist or has been moved. Check the URL
        and try again.
      </p>
      <Link to="/">
        <Button variant="outline" className="gap-2">
          <ArrowLeft size={14} aria-hidden="true" />
          Back to Dashboard
        </Button>
      </Link>
    </div>
  );
}
