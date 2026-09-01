import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { API_BASE_URL } from '../utils/apiConfig';

const parseLicenseEndMs = (value) => {
  if (!value) return null;
  const text = String(value).trim();
  if (!text) return null;
  const parsed = new Date(text).getTime();
  if (!Number.isNaN(parsed)) return parsed;
  const match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!match) return null;
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  if (day < 1 || day > 31 || month < 1 || month > 12) return null;
  return Date.UTC(year, month - 1, day, 23, 59, 59, 999);
};

const normalizeUser = (data = {}) => ({
  username: data.username,
  role: data.role,
  email: data.email,
  assigned_menus: data.assigned_menus || [],
  assigned_cameras: data.assigned_cameras || [],
  max_users_limit: Number(data.max_users_limit || 0),
  max_cameras_limit: Number(data.max_cameras_limit || 0),
  company_id: data.company_id || null,
  license_start_date: data.license_start_date || null,
  license_end_date: data.license_end_date || null,
  is_active: data.is_active !== false,
});

const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      tokenExpiresAt: null,
      company_id: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (username, password, role = null, skipAuthUpdate = false) => {
        set({ isLoading: true, error: null });
        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), 10000);
        try {
          const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, role }),
            signal: controller.signal,
          });
          window.clearTimeout(timeoutId);
          if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: 'Login failed' }));
            throw new Error(payload.detail || 'Login failed');
          }

          const data = await response.json();
          const expiresInSeconds = Number(data.expires_in || 3600);
          const tokenExpiresAt = Date.now() + Math.max(60, expiresInSeconds) * 1000;
          const user = normalizeUser(data);

          set({
            user,
            token: data.access_token,
            tokenExpiresAt,
            company_id: user.company_id,
            isAuthenticated: !skipAuthUpdate,
            isLoading: false,
            error: null,
          });

          localStorage.setItem('auth_token', data.access_token);
          if (window?.electronAPI?.setAuthToken) {
            window.electronAPI.setAuthToken(data.access_token).catch(() => {});
          }
          return { success: true, role: user.role, username: user.username, company_id: user.company_id };
        } catch (loginError) {
          window.clearTimeout(timeoutId);
          const message = loginError.name === 'AbortError'
            ? 'Connection timed out. Check the backend connection and try again.'
            : (loginError.message || 'Login failed');
          set({ isLoading: false, error: message });
          return { success: false, error: message };
        }
      },

      setAuthenticated: (isAuthenticated) => set({ isAuthenticated }),

      isSessionExpired: () => {
        const { token, tokenExpiresAt } = get();
        if (!token) return true;
        return !!tokenExpiresAt && tokenExpiresAt <= Date.now();
      },

      getAuthHeaders: () => {
        const { token } = get();
        return token ? { Authorization: `Bearer ${token}` } : {};
      },

      logout: () => {
        const { token } = get();
        if (token) {
          fetch(`${API_BASE_URL}/api/auth/logout`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
          }).catch(() => {});
        }
        set({
          user: null,
          token: null,
          tokenExpiresAt: null,
          company_id: null,
          isAuthenticated: false,
          error: null,
        });
        localStorage.removeItem('auth_token');
        if (window?.electronAPI?.clearAuthToken) {
          window.electronAPI.clearAuthToken().catch(() => {});
        }
      },

      clearError: () => set({ error: null }),

      getCurrentUser: async () => {
        const { token } = get();
        if (!token || get().isSessionExpired()) {
          if (token) get().logout();
          return null;
        }

        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), 10000);
        try {
          const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          });
          window.clearTimeout(timeoutId);
          if (!response.ok) {
            get().logout();
            return null;
          }
          const userData = normalizeUser(await response.json());
          set({ user: userData, company_id: userData.company_id, isAuthenticated: true });
          return userData;
        } catch (requestError) {
          window.clearTimeout(timeoutId);
          if (requestError.name !== 'AbortError') console.error('Error fetching current user:', requestError);
          return null;
        }
      },

      hasRole: (role) => get().user?.role === role,
      hasAnyRole: (roles) => roles.includes(get().user?.role),
      canManageUsers: () => ['SuperAdmin', 'Admin'].includes(get().user?.role),
      canManageCameras: () => ['SuperAdmin', 'Admin'].includes(get().user?.role),
      canDelete: () => get().user?.role === 'SuperAdmin',
      getAssignedCameras: () => get().user?.assigned_cameras || [],
      getAssignedMenus: () => get().user?.assigned_menus || [],
      getTenantLimits: () => ({
        users: Number(get().user?.max_users_limit || 0),
        cameras: Number(get().user?.max_cameras_limit || 0),
      }),
      hasMenuAccess: (menu) => {
        if (get().user?.role === 'SuperAdmin') return true;
        const aliases = {
          cameras: 'camera',
          admin: 'users',
          backupmgmt: 'backup',
          'attendance-report': 'attendance',
          'day-report': 'attendance',
          'week-report': 'attendance',
          'month-report': 'attendance',
        };
        const target = aliases[menu] || menu;
        const menus = (get().user?.assigned_menus || []).map((value) => aliases[value] || value);
        return menus.includes(target);
      },
      isLicenseExpired: () => {
        const user = get().user;
        if (!user || user.role === 'SuperAdmin') return false;
        if (!user.license_end_date) return false;
        const endMs = parseLicenseEndMs(user.license_end_date);
        return endMs === null || endMs < Date.now();
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        tokenExpiresAt: state.tokenExpiresAt,
        company_id: state.company_id,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
);

export default useAuthStore;
