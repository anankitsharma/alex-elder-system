# Phase 8: Frontend Authentication + UI

## New Pages

### Login Page (`frontend/src/app/login/page.tsx`)

```
┌─────────────────────────────┐
│     Elder Trading System    │
│                             │
│  Email:    [____________]   │
│  Password: [____________]   │
│                             │
│       [  Login  ]           │
│                             │
│  Don't have an account?     │
│  Contact admin              │
└─────────────────────────────┘
```

No self-registration — admin creates accounts. Login page only.

### Settings Page — Broker Credentials Section

```
┌─────────────────────────────────────────────┐
│  Angel One Credentials                      │
│                                             │
│  API Key:      [________________________]   │
│  Secret Key:   [________________________]   │
│  Client Code:  [____________]               │
│  Password:     [____________]               │
│  TOTP Secret:  [________________________]   │
│                                             │
│  [  Save & Validate  ]   Status: Connected  │
└─────────────────────────────────────────────┘
```

### Settings Page — Notification Section

```
┌─────────────────────────────────────────────┐
│  Notifications                              │
│                                             │
│  Telegram Chat ID: [____________]           │
│  Discord Webhook:  [________________________│
│                                             │
│  Min Priority: [NORMAL ▼]                   │
│  Alerts Enabled: [✓]                        │
│                                             │
│  [  Save  ]  [  Test Notification  ]        │
└─────────────────────────────────────────────┘
```

## Auth State Management

### New file: `frontend/src/store/useAuthStore.ts`

```typescript
import { create } from 'zustand';

interface AuthState {
    user: User | null;
    token: string | null;
    isAuthenticated: boolean;
    login: (email: string, password: string) => Promise<boolean>;
    logout: () => void;
    checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
    user: null,
    token: localStorage.getItem('access_token'),
    isAuthenticated: !!localStorage.getItem('access_token'),

    login: async (email, password) => {
        const res = await fetch(`${API_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username: email, password }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        localStorage.setItem('access_token', data.access_token);
        set({ token: data.access_token, isAuthenticated: true });
        await get().checkAuth();
        return true;
    },

    logout: () => {
        localStorage.removeItem('access_token');
        set({ user: null, token: null, isAuthenticated: false });
        window.location.href = '/login';
    },

    checkAuth: async () => {
        const token = get().token;
        if (!token) return;
        const res = await fetch(`${API_URL}/api/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (res.ok) {
            const user = await res.json();
            set({ user, isAuthenticated: true });
        } else {
            get().logout();
        }
    },
}));
```

## API Client Changes (`lib/api.ts`)

Add Authorization header to all requests:

```typescript
export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
    const token = localStorage.getItem('access_token');

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> || {}),
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${BASE_URL}${url}`, {
        ...options,
        headers,
    });

    // Handle 401 — redirect to login
    if (response.status === 401) {
        localStorage.removeItem('access_token');
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }

    return response.json();
}
```

## WebSocket Changes (`lib/websocketManager.ts`)

Pass token in query parameter:

```typescript
const token = localStorage.getItem('access_token');
const wsUrl = `${WS_BASE}/ws/pipeline?token=${token}`;
this.pipelineWs = new WebSocket(wsUrl);

// Handle auth rejection
this.pipelineWs.onclose = (event) => {
    if (event.code === 4001) {
        // Auth failed
        window.location.href = '/login';
        return;
    }
    // Normal reconnect logic...
};
```

## Protected Route Wrapper

```typescript
// frontend/src/components/layout/AuthGuard.tsx
'use client';
import { useEffect } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { useRouter } from 'next/navigation';

export function AuthGuard({ children }: { children: React.ReactNode }) {
    const { isAuthenticated, checkAuth } = useAuthStore();
    const router = useRouter();

    useEffect(() => {
        if (!isAuthenticated) {
            router.push('/login');
        } else {
            checkAuth(); // Verify token is still valid
        }
    }, [isAuthenticated]);

    if (!isAuthenticated) return null;
    return <>{children}</>;
}
```

Wrap `page.tsx`:
```tsx
export default function Home() {
    return (
        <AuthGuard>
            {/* Existing dashboard content */}
        </AuthGuard>
    );
}
```

## Sidebar User Info

Add user display to sidebar bottom:

```
┌──────────┐
│  📊 Dashboard │
│  📈 Charts    │
│  ...          │
│               │
│  ───────────  │
│  👤 Admin     │
│  PAPER mode   │
│  [Logout]     │
└──────────────┘
```

## Admin Panel (Phase 8b — Optional)

For superuser only:
- User management (create/disable users)
- View all users' positions (read-only)
- System health dashboard
- Global settings management
