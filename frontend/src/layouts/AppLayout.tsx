import { Outlet } from "react-router-dom";
import { LeftRail } from "@/components/nav/LeftRail";
import { MobileNav } from "@/components/nav/MobileNav";
import { useAuth } from "@/hooks/use-auth";

/**
 * Standard application layout — dark left rail + light main content canvas.
 * Every screen except the Live Run view uses this layout.
 */
export function AppLayout() {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div className="min-h-screen bg-canvas">
      {/* Desktop left rail */}
      <LeftRail user={user} />

      {/* Main content — offset by rail width on desktop */}
      <main
        id="main-content"
        className="workspace-canvas min-h-screen lg:ml-56"
        tabIndex={-1}
      >
        {/* Skip to content link for keyboard users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-canvas"
        >
          Skip to main content
        </a>

        <div className="mx-auto max-w-7xl px-4 pb-20 pt-8 sm:px-6 lg:pb-8">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom navigation */}
      <MobileNav />
    </div>
  );
}
