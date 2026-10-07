import { Outlet } from "react-router-dom";

/**
 * Full-bleed layout for the Live Run screen.
 *
 * Breaks the standard left-rail chrome so the screenshot + Perception Overlay
 * can dominate the entire viewport. This is the one deliberate exception to
 * the standard layout — see Section 3 of the design spec.
 */
export function FullBleedLayout() {
  return (
    <div className="theme-dark fixed inset-0 bg-graphite-950">
      <Outlet />
    </div>
  );
}
