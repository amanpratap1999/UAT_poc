import { Outlet } from "react-router-dom";
import { LeftRail } from "@/components/nav/LeftRail";
import { MobileNav } from "@/components/nav/MobileNav";
import { useAuth } from "@/hooks/use-auth";

/**
 * Standard application layout — left rail + main content canvas.
 * Every screen except the Live Run view uses this layout.
 */
export function AppLayout() {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div className="min-h-screen bg-graphite-950">
      {/* Desktop left rail */}
      <LeftRail user={user} />

      {/* Main content — offset by rail width on desktop */}
      <main
        id="main-content"
        className="min-h-screen lg:ml-56"
        tabIndex={-1}
      >
        {/* Skip to content link for keyboard users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-signal-teal focus:px-3 focus:py-2 focus:text-graphite-950"
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
