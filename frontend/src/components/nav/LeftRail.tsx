import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  PlayCircle,
  AlertTriangle,
  BookOpen,
  Settings,
  LogOut,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import type { UserContext } from "@/types/auth";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, id: "nav-dashboard" },
  { to: "/runs", label: "Runs", icon: PlayCircle, id: "nav-runs" },
  { to: "/findings", label: "Findings", icon: AlertTriangle, id: "nav-findings" },
  { to: "/knowledge", label: "Knowledge Model", icon: BookOpen, id: "nav-knowledge" },
  { to: "/settings", label: "Settings", icon: Settings, id: "nav-settings" },
] as const;

interface NavItemProps {
  to: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  id: string;
}

function NavItem({ to, label, icon: Icon, id }: NavItemProps) {
  return (
    <NavLink
      to={to}
      id={id}
      end={to === "/"}
      className={({ isActive }) =>
        cn(
          "group flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors",
          isActive
            ? "bg-graphite-600/60 text-ink-100"
            : "text-ink-400 hover:bg-graphite-800 hover:text-ink-100"
        )
      }
    >
      <Icon
        size={16}
        className="shrink-0 transition-colors group-hover:text-ink-100"
      />
      <span className="truncate font-body">{label}</span>
    </NavLink>
  );
}

interface LeftRailProps {
  user: UserContext;
}

export function LeftRail({ user }: LeftRailProps) {
  const { logout } = useAuth();

  return (
    <aside
      className="fixed left-0 top-0 z-30 hidden h-full w-56 flex-col border-r border-graphite-600 bg-graphite-800 lg:flex"
      aria-label="Primary navigation"
    >
      {/* Product identity */}
      <div className="flex h-14 items-center gap-2.5 border-b border-graphite-600 px-4">
        <Zap size={16} className="shrink-0 text-signal-teal" aria-hidden="true" />
        <span className="font-display text-sm font-semibold tracking-tight text-ink-100">
          QA Engine
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-3" aria-label="Main navigation">
        <ul role="list" className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavItem {...item} />
            </li>
          ))}
        </ul>
      </nav>

      {/* User / logout */}
      <div className="border-t border-graphite-600 p-3">
        <div className="mb-2 px-3 py-1">
          <p className="truncate font-mono text-xs font-medium text-ink-100">{user.username}</p>
          <p className="font-mono text-2xs text-ink-400">{user.role}</p>
        </div>
        <button
          onClick={logout}
          id="nav-logout"
          className="flex w-full items-center gap-3 rounded px-3 py-2 text-sm text-ink-400 transition-colors hover:bg-graphite-800 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
        >
          <LogOut size={16} aria-hidden="true" />
          <span className="font-body">Sign out</span>
        </button>
      </div>
    </aside>
  );
}
