import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  PlayCircle,
  AlertTriangle,
  BookOpen,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const MOB_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, id: "mob-nav-dashboard" },
  { to: "/runs", label: "Runs", icon: PlayCircle, id: "mob-nav-runs" },
  { to: "/findings", label: "Findings", icon: AlertTriangle, id: "mob-nav-findings" },
  { to: "/knowledge", label: "Knowledge", icon: BookOpen, id: "mob-nav-knowledge" },
  { to: "/settings", label: "Settings", icon: Settings, id: "mob-nav-settings" },
] as const;

export function MobileNav() {
  return (
    <nav
      className="theme-dark fixed bottom-0 left-0 right-0 z-30 border-t border-graphite-600/70 bg-graphite-950/95 backdrop-blur lg:hidden"
      aria-label="Mobile navigation"
    >
      <ul role="list" className="flex">
        {MOB_ITEMS.map(({ to, label, icon: Icon, id }) => (
          <li key={to} className="flex-1">
            <NavLink
              to={to}
              end={to === "/"}
              id={id}
              className={({ isActive }) =>
                cn(
                  "flex flex-col items-center gap-1 py-3 text-center transition-colors",
                  isActive ? "text-signal-teal" : "text-ink-400 hover:text-ink-100"
                )
              }
            >
              <Icon size={18} aria-hidden="true" />
              <span className="font-body text-2xs">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
