"use client";

import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";
import {
  LayoutDashboard,
  BarChart3,
  ArrowLeftRight,
  Zap,
  Shield,
  Wallet,
  Settings2,
  Sun,
  Moon,
} from "lucide-react";

export type ViewId = "dashboard" | "charts" | "trades" | "signals" | "risk" | "portfolio" | "settings";

const NAV: { id: ViewId; icon: typeof LayoutDashboard; label: string }[] = [
  { id: "dashboard", icon: LayoutDashboard, label: "Overview" },
  { id: "charts",    icon: BarChart3,       label: "Charts" },
  { id: "trades",    icon: ArrowLeftRight,  label: "Trades" },
  { id: "signals",   icon: Zap,             label: "Signals" },
  { id: "risk",      icon: Shield,          label: "Risk" },
  { id: "portfolio", icon: Wallet,          label: "Portfolio" },
];

/* Tooltip shared classes */
const TIP = "absolute left-full ml-3 px-2.5 py-1 rounded-md bg-tooltip border border-tooltip-border text-[10px] text-tooltip-text whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-100 z-50 shadow-xl shadow-black/40";

export function Sidebar({
  active,
  onChange,
}: {
  active: ViewId;
  onChange: (v: ViewId) => void;
}) {
  const { theme, toggle } = useTheme();

  return (
    <nav className="flex flex-col items-center w-[54px] border-r border-border py-3 gap-0.5 bg-sidebar shrink-0">
      {/* Brand mark */}
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent/25 to-accent/5 border border-accent/15 flex items-center justify-center mb-6 select-none">
        <span className="text-accent font-bold text-[13px] font-mono leading-none">E</span>
      </div>

      {NAV.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          title={label}
          className={cn(
            "relative w-9 h-9 rounded-md flex items-center justify-center transition-all duration-150 group",
            active === id
              ? "bg-accent/10 text-accent"
              : "text-sidebar-muted hover:text-sidebar-hover hover:bg-sidebar-active"
          )}
        >
          <Icon className="w-[17px] h-[17px]" />
          <span className={TIP}>{label}</span>
          {active === id && (
            <span className="absolute -left-px top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-r-full bg-accent" />
          )}
        </button>
      ))}

      {/* Bottom spacer */}
      <div className="flex-1" />

      {/* Theme toggle */}
      <button
        onClick={toggle}
        title={theme === "dark" ? "Switch to light" : "Switch to dark"}
        className="relative w-9 h-9 rounded-md flex items-center justify-center transition-all duration-150 group text-sidebar-muted hover:text-sidebar-hover hover:bg-sidebar-active mb-1"
      >
        {theme === "dark" ? (
          <Sun className="w-[16px] h-[16px]" />
        ) : (
          <Moon className="w-[16px] h-[16px]" />
        )}
        <span className={TIP}>
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </span>
      </button>

      {/* Divider */}
      <div className="w-6 h-px bg-border mb-2" />

      {/* Settings — pinned to bottom */}
      <button
        onClick={() => onChange("settings")}
        title="Settings"
        className={cn(
          "relative w-9 h-9 rounded-md flex items-center justify-center transition-all duration-150 group mb-2",
          active === "settings"
            ? "bg-accent/10 text-accent"
            : "text-sidebar-muted hover:text-sidebar-hover hover:bg-sidebar-active"
        )}
      >
        <Settings2 className="w-[17px] h-[17px]" />
        <span className={TIP}>Settings</span>
        {active === "settings" && (
          <span className="absolute -left-px top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-r-full bg-accent" />
        )}
      </button>

      <div className="w-6 h-6 rounded-full bg-accent/8 border border-accent/10 flex items-center justify-center text-[9px] text-accent/60 font-mono select-none" title="v0.3">
        3
      </div>
    </nav>
  );
}
