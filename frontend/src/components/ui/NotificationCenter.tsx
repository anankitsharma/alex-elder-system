"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import { Bell, Check, CheckCheck, Trash2, X } from "lucide-react";
import {
  useNotificationStore,
  requestPushPermission,
} from "@/store/useNotificationStore";
import type {
  AppNotification,
  NotificationCategory,
} from "@/store/useNotificationStore";

// ── Time formatting ─────────────────────────────────────────

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return "now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const d = Math.floor(hr / 24);
  return `${d}d`;
}

// ── Category styling ────────────────────────────────────────

const CATEGORY_STYLES: Record<
  NotificationCategory,
  { bg: string; text: string; label: string }
> = {
  signal:   { bg: "bg-amber/10",  text: "text-amber",  label: "Signal" },
  trade:    { bg: "bg-green/10",  text: "text-green",  label: "Trade" },
  position: { bg: "bg-blue/10",   text: "text-blue",   label: "Position" },
  risk:     { bg: "bg-red/10",    text: "text-red",    label: "Risk" },
  system:   { bg: "bg-accent/10", text: "text-accent", label: "System" },
  error:    { bg: "bg-red/10",    text: "text-red",    label: "Error" },
};

// Priority border accents
const PRIORITY_BORDER: Record<string, string> = {
  critical: "border-l-red",
  high: "border-l-amber",
  normal: "border-l-transparent",
  low: "border-l-transparent",
};

// ── Filter tabs ─────────────────────────────────────────────

type FilterKey = "all" | NotificationCategory;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all",      label: "All" },
  { key: "signal",   label: "Signals" },
  { key: "trade",    label: "Trades" },
  { key: "position", label: "Positions" },
  { key: "error",    label: "Errors" },
];

// ── Single notification row ─────────────────────────────────

function NotificationRow({
  n,
  onRead,
  onRemove,
}: {
  n: AppNotification;
  onRead: () => void;
  onRemove: () => void;
}) {
  const cat = CATEGORY_STYLES[n.category] || CATEGORY_STYLES.system;
  const borderClass = PRIORITY_BORDER[n.priority] || "border-l-transparent";

  return (
    <div
      onClick={onRead}
      className={cn(
        "group relative px-3 py-2.5 border-l-2 cursor-pointer transition-colors duration-100",
        borderClass,
        n.read
          ? "opacity-60 hover:opacity-80"
          : "hover:bg-surface-2/50",
      )}
    >
      {/* Unread dot */}
      {!n.read && (
        <span className="absolute top-3 right-3 w-1.5 h-1.5 rounded-full bg-accent animate-pulse-dot" />
      )}

      {/* Remove button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-muted hover:text-red transition-opacity"
      >
        <X className="w-3 h-3" />
      </button>

      {/* Header: icon + title + time */}
      <div className="flex items-start gap-2">
        <span className="text-sm leading-none mt-0.5 shrink-0">{n.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-foreground truncate">
              {n.title}
            </span>
            {n.symbol && (
              <span className={cn("text-[9px] px-1 py-px rounded font-mono", cat.bg, cat.text)}>
                {n.symbol}
              </span>
            )}
          </div>

          <p className="text-[10px] text-muted mt-0.5 leading-snug">{n.message}</p>

          {n.detail && (
            <p className="text-[9px] text-muted/70 mt-0.5">{n.detail}</p>
          )}

          {/* P&L display */}
          {n.pnl !== undefined && n.pnl !== null && (
            <span
              className={cn(
                "inline-block text-[10px] font-bold mt-1",
                n.pnl > 0 ? "text-green" : n.pnl < 0 ? "text-red" : "text-muted",
              )}
            >
              {n.pnl > 0 ? "+" : ""}
              {n.pnl.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
            </span>
          )}
        </div>

        <span className="text-[9px] text-muted/60 tabular-nums shrink-0 mt-0.5">
          {timeAgo(n.timestamp)}
        </span>
      </div>
    </div>
  );
}

// ── Main NotificationCenter ─────────────────────────────────

export function NotificationBell() {
  const { unreadCount, panelOpen, togglePanel } = useNotificationStore();

  // Request push permission on first render
  useEffect(() => {
    requestPushPermission();
  }, []);

  // Load stored notifications
  useEffect(() => {
    useNotificationStore.getState().loadStored();
  }, []);

  return (
    <div className="relative">
      <button
        onClick={togglePanel}
        className={cn(
          "relative w-9 h-9 rounded-md flex items-center justify-center transition-all duration-150 group",
          panelOpen
            ? "bg-accent/10 text-accent"
            : "text-sidebar-muted hover:text-sidebar-hover hover:bg-sidebar-active",
        )}
      >
        <Bell className="w-[17px] h-[17px]" />

        {/* Badge */}
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red text-[9px] font-bold text-white flex items-center justify-center leading-none tabular-nums">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {panelOpen && <NotificationPanel />}
    </div>
  );
}

function NotificationPanel() {
  const {
    notifications,
    unreadCount,
    markRead,
    markAllRead,
    clearAll,
    removeNotification,
    closePanel,
  } = useNotificationStore();

  const [filter, setFilter] = useState<FilterKey>("all");
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        // Check if clicking the bell button itself
        const bell = (e.target as Element)?.closest?.("[data-notification-bell]");
        if (!bell) closePanel();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [closePanel]);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") closePanel();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [closePanel]);

  const filtered =
    filter === "all"
      ? notifications
      : notifications.filter((n) => n.category === filter);

  // Group by date
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();

  function dateLabel(ts: number): string {
    const d = new Date(ts).toDateString();
    if (d === today) return "Today";
    if (d === yesterday) return "Yesterday";
    return new Date(ts).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
    });
  }

  // Group into sections
  const groups: { label: string; items: AppNotification[] }[] = [];
  for (const n of filtered) {
    const label = dateLabel(n.timestamp);
    const last = groups[groups.length - 1];
    if (last && last.label === label) {
      last.items.push(n);
    } else {
      groups.push({ label, items: [n] });
    }
  }

  return (
    <div
      ref={panelRef}
      className={cn(
        "absolute left-full top-0 ml-3 w-[340px] max-h-[calc(100vh-80px)]",
        "bg-surface border border-border rounded-lg shadow-2xl shadow-black/50",
        "flex flex-col z-[100] overflow-hidden",
        "animate-in slide-in-from-left-2 fade-in duration-150",
      )}
    >
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-border shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-bold text-foreground tracking-wide">
              Notifications
            </h3>
            {unreadCount > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-accent/10 text-accent font-semibold tabular-nums">
                {unreadCount} new
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                title="Mark all read"
                className="p-1 rounded text-muted hover:text-accent hover:bg-accent/5 transition-colors"
              >
                <CheckCheck className="w-3.5 h-3.5" />
              </button>
            )}
            {notifications.length > 0 && (
              <button
                onClick={clearAll}
                title="Clear all"
                className="p-1 rounded text-muted hover:text-red hover:bg-red/5 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={closePanel}
              className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-2 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-0.5">
          {FILTERS.map(({ key, label }) => {
            const count =
              key === "all"
                ? notifications.length
                : notifications.filter((n) => n.category === key).length;
            return (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={cn(
                  "px-2 py-1 rounded text-[10px] font-medium transition-colors",
                  filter === key
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:text-foreground hover:bg-surface-2",
                  count === 0 && key !== "all" && "opacity-40",
                )}
              >
                {label}
                {count > 0 && key !== "all" && (
                  <span className="ml-1 text-[8px] opacity-60">{count}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Notification list */}
      <div className="flex-1 overflow-y-auto overscroll-contain min-h-0">
        {groups.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 px-4">
            <div className="w-10 h-10 rounded-full bg-surface-2 flex items-center justify-center mb-3">
              <Bell className="w-5 h-5 text-muted/40" />
            </div>
            <p className="text-xs text-muted/60 text-center">
              No notifications yet
            </p>
            <p className="text-[10px] text-muted/40 text-center mt-1">
              Trade signals, executions, and alerts will appear here
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label}>
              <div className="sticky top-0 z-10 px-3 py-1.5 text-[9px] font-semibold text-muted/50 uppercase tracking-widest bg-surface/95 backdrop-blur-sm border-b border-border/50">
                {group.label}
              </div>
              <div className="divide-y divide-border/30">
                {group.items.map((n) => (
                  <NotificationRow
                    key={n.id}
                    n={n}
                    onRead={() => markRead(n.id)}
                    onRemove={() => removeNotification(n.id)}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
