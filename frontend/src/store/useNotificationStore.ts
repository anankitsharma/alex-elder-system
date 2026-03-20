import { create } from "zustand";

// ── Notification Types ──────────────────────────────────────

export type NotificationCategory =
  | "signal"
  | "trade"
  | "position"
  | "risk"
  | "system"
  | "error";

export type NotificationPriority = "low" | "normal" | "high" | "critical";

export interface AppNotification {
  id: string;
  category: NotificationCategory;
  priority: NotificationPriority;
  title: string;
  message: string;
  detail?: string;
  symbol?: string;
  pnl?: number;
  timestamp: number; // epoch ms
  read: boolean;
  icon: string;
}

// ── Browser Push Notifications ──────────────────────────────

let _pushPermission: NotificationPermission = "default";

export async function requestPushPermission(): Promise<boolean> {
  if (typeof window === "undefined" || !("Notification" in window)) return false;
  if (Notification.permission === "granted") {
    _pushPermission = "granted";
    return true;
  }
  if (Notification.permission === "denied") return false;

  const result = await Notification.requestPermission();
  _pushPermission = result;
  return result === "granted";
}

function sendBrowserNotification(title: string, body: string, icon?: string): void {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;

  // Only send if tab is not focused (avoid double notification)
  if (!document.hidden) return;

  try {
    const n = new Notification(title, {
      body,
      icon: icon || "/favicon.ico",
      badge: "/favicon.ico",
      tag: `elder-${Date.now()}`,
      silent: false,
    });
    // Auto-close after 8s
    setTimeout(() => n.close(), 8000);
    // Focus tab on click
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // Notification API not available
  }
}

// ── Persistence ─────────────────────────────────────────────

const STORAGE_KEY = "elder_notifications";
const MAX_STORED = 200;

function loadFromStorage(): AppNotification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AppNotification[];
    return Array.isArray(parsed) ? parsed.slice(0, MAX_STORED) : [];
  } catch {
    return [];
  }
}

function saveToStorage(notifications: AppNotification[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(0, MAX_STORED)));
  } catch {
    // Storage full — clear and retry
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(0, 50)));
    } catch {
      // Give up
    }
  }
}

// ── Priority → Browser Push mapping ─────────────────────────

const PUSH_PRIORITIES = new Set<NotificationPriority>(["high", "critical"]);

// ── Store ───────────────────────────────────────────────────

interface NotificationStore {
  notifications: AppNotification[];
  unreadCount: number;
  panelOpen: boolean;

  // Actions
  addNotification: (n: Omit<AppNotification, "id" | "timestamp" | "read">) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
  removeNotification: (id: string) => void;
  togglePanel: () => void;
  closePanel: () => void;
  loadStored: () => void;
}

let _idCounter = 0;

export const useNotificationStore = create<NotificationStore>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  panelOpen: false,

  addNotification: (n) => {
    const notification: AppNotification = {
      ...n,
      id: `notif-${Date.now()}-${++_idCounter}`,
      timestamp: Date.now(),
      read: false,
    };

    set((state) => {
      const updated = [notification, ...state.notifications].slice(0, MAX_STORED);
      const unread = updated.filter((x) => !x.read).length;
      saveToStorage(updated);
      return { notifications: updated, unreadCount: unread };
    });

    // Browser push for high/critical priority
    if (PUSH_PRIORITIES.has(n.priority)) {
      sendBrowserNotification(
        `${n.icon} ${n.title}`,
        n.message + (n.detail ? `\n${n.detail}` : ""),
      );
    }
  },

  markRead: (id) => {
    set((state) => {
      const updated = state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n,
      );
      const unread = updated.filter((x) => !x.read).length;
      saveToStorage(updated);
      return { notifications: updated, unreadCount: unread };
    });
  },

  markAllRead: () => {
    set((state) => {
      const updated = state.notifications.map((n) => ({ ...n, read: true }));
      saveToStorage(updated);
      return { notifications: updated, unreadCount: 0 };
    });
  },

  clearAll: () => {
    saveToStorage([]);
    set({ notifications: [], unreadCount: 0 });
  },

  removeNotification: (id) => {
    set((state) => {
      const updated = state.notifications.filter((n) => n.id !== id);
      const unread = updated.filter((x) => !x.read).length;
      saveToStorage(updated);
      return { notifications: updated, unreadCount: unread };
    });
  },

  togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
  closePanel: () => set({ panelOpen: false }),

  loadStored: () => {
    const stored = loadFromStorage();
    const unread = stored.filter((x) => !x.read).length;
    set({ notifications: stored, unreadCount: unread });
  },
}));
