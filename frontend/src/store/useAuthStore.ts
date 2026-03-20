import { create } from 'zustand';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface User {
  id: number;
  email: string;
  username: string;
  full_name: string;
  role: string;
  trading_mode: string;
  approved_for_live: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: typeof window !== 'undefined' ? localStorage.getItem('elder_token') : null,
  isAuthenticated: typeof window !== 'undefined' ? !!localStorage.getItem('elder_token') : false,
  loading: true,

  login: async (username, password) => {
    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username, password }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      localStorage.setItem('elder_token', data.access_token);
      set({ token: data.access_token, isAuthenticated: true });
      await get().checkAuth();
      return true;
    } catch {
      return false;
    }
  },

  logout: () => {
    localStorage.removeItem('elder_token');
    set({ user: null, token: null, isAuthenticated: false });
  },

  checkAuth: async () => {
    const token = get().token;
    if (!token) { set({ loading: false }); return; }
    try {
      const res = await fetch(`${API_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const user = await res.json();
        set({ user, isAuthenticated: true, loading: false });
      } else {
        get().logout();
        set({ loading: false });
      }
    } catch {
      set({ loading: false });
    }
  },
}));
