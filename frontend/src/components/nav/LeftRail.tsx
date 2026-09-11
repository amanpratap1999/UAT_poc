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

const NAV_SECTIONS: {
  label: string;
  items: {
    to: string;
    label: string;
    icon: React.ComponentType<{ size?: number; className?: string }>;
    id: string;
  }[];
}[] = [
  {
    label: "Monitor",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, id: "nav-dashboard" },
      { to: "/runs", label: "Runs", icon: PlayCircle, id: "nav-runs" },
      { to: "/findings", label: "Findings", icon: AlertTriangle, id: "nav-findings" },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/knowledge", label: "Knowledge Model", icon: BookOpen, id: "nav-knowledge" },
      { to: "/settings", label: "Settings", icon: Settings, id: "nav-settings" },
    ],
  },
];

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
          "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
          isActive
            ? "bg-white/8 font-medium text-ink-100"
            : "text-ink-400 hover:bg-white/5 hover:text-ink-100"
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* Active indicator — left edge bar */}
          <span
            aria-hidden="true"
            className={cn(
              "absolute -left-3 top-1/2 h-5 w-1 -translate-y-1/2 rounded-full bg-signal-teal transition-opacity duration-150",
              isActive ? "opacity-100" : "opacity-0"
            )}
          />
          <Icon
            size={16}
            className={cn(
              "shrink-0 transition-colors",
              isActive ? "text-ink-100" : "text-ink-600 group-hover:text-ink-400"
            )}
          />
          <span className="truncate font-body">{label}</span>
        </>
      )}
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
      className="theme-dark fixed left-0 top-0 z-30 hidden h-full w-56 flex-col border-r border-graphite-600/70 bg-graphite-950 lg:flex"
      aria-label="Primary navigation"
    >
      {/* Product identity */}
      <div className="flex h-14 items-center gap-2.5 border-b border-graphite-600/70 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-signal-teal/10">
          <Zap size={15} className="shrink-0 text-signal-teal" aria-hidden="true" />
        </div>
        <div className="flex flex-col">
          <span className="font-display text-sm font-semibold tracking-tight text-ink-100">
            QA Engine
          </span>
          <span className="font-mono text-3xs uppercase tracking-[0.14em] text-ink-600">
            ServiceNow
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Main navigation">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label} className="mb-5">
            <p className="mb-1.5 px-3 font-mono text-3xs font-semibold uppercase tracking-[0.14em] text-ink-600">
              {section.label}
            </p>
            <ul role="list" className="flex flex-col gap-0.5">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavItem {...item} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* User / logout */}
      <div className="border-t border-graphite-600/70 p-3">
        <div className="mb-2 flex items-center gap-2.5 rounded-md px-2 py-1.5">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-graphite-600 bg-graphite-800 font-mono text-xs font-semibold text-signal-teal"
            aria-hidden="true"
          >
            {user.username.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="truncate font-body text-xs font-medium text-ink-100">{user.username}</p>
            <p className="font-mono text-3xs uppercase tracking-wider text-ink-600">{user.role}</p>
          </div>
        </div>
        <button
          onClick={logout}
          id="nav-logout"
          className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-ink-400 transition-colors hover:bg-white/5 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
        >
          <LogOut size={16} aria-hidden="true" />
          <span className="font-body">Sign out</span>
        </button>
      </div>
    </aside>
  );
}
