import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="workspace-canvas flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas text-center">
      <p className="font-mono text-6xl font-light text-faint">404</p>
      <h1 className="page-title">Page not found</h1>
      <p className="max-w-xs text-sm text-body">
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
