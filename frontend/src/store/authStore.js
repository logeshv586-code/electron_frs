import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { API_BASE_URL } from '../utils/apiConfig';

const parseLicenseEndMs = (value) => {
  if (!value) return null;
  const s = String(value).trim();
  if (!s) return null;

  const dt = new Date(s);
  const ms = dt.getTime();
  if (!Number.isNaN(ms)) return ms;

  const m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m) {
    const day = parseInt(m[1], 10);
    const month = parseInt(m[2], 10);
    const year = parseInt(m[3], 10);
    if (day >= 1 && day <= 31 && month >= 1 && month <= 12) {
      return Date.UTC(year, month - 1, day, 23, 59, 59, 999);
    }
  }

  return null;
};

const useAuthStore = create(
  persist(
    (set, get) => ({
      // State
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      // Actions
      login: async (username, password, role, skipAuthUpdate = false) => {
        set({ isLoading: true, error: null });

        try {
          const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password, role }),
          });

          if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Login failed' }));
            throw new Error(errorData.detail || 'Login failed');
          }

          const data = await response.json();

          const newState = {
            user: {
              username: data.username,
              role: data.role,
              assigned_menus: data.assigned_menus,
              company_id: data.company_id,
              license_start_date: data.license_start_date,
              license_end_date: data.license_end_date,
            },
            token: data.access_token,
            isAuthenticated: !skipAuthUpdate,
            isLoading: false,
            error: null,
          };

          set(newState);

          // Store token in localStorage for global fetch shim
          localStorage.setItem('auth_token', data.access_token);
          if (window && window.electronAPI && typeof window.electronAPI.setAuthToken === 'function') {
            window.electronAPI.setAuthToken(data.access_token).catch(() => { });
          }

          return { success: true };
        } catch (error) {
          set({
            isLoading: false,
            error: error.message,
          });
          return { success: false, error: error.message };
        }
      },

      setAuthenticated: (isAuthenticated) => {
        set({ isAuthenticated });
      },

      logout: () => {
        const { token } = get();
        // Attempt server-side revocation
        if (token) {
          fetch(`${API_BASE_URL}/api/auth/logout`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`
            }
          }).catch(() => { });
        }
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          error: null,
        });
        localStorage.removeItem('auth_token');
        if (window && window.electronAPI && typeof window.electronAPI.clearAuthToken === 'function') {
          window.electronAPI.clearAuthToken().catch(() => { });
        }
      },

      clearError: () => {
        set({ error: null });
      },

      getCurrentUser: async () => {
        const { token } = get();
        if (!token) return null;

        try {
          const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          });

          if (response.ok) {
            const userData = await response.json();
            set({ user: userData });
            return userData;
          } else {
            // Token is invalid, logout
            get().logout();
            return null;
          }
        } catch (error) {
          console.error('Error fetching current user:', error);
          return null;
        }
      },

      // Helper methods
      hasRole: (role) => {
        const { user } = get();
        return user?.role === role;
      },

      hasAnyRole: (roles) => {
        const { user } = get();
        return roles.includes(user?.role);
      },

      canManageUsers: () => {
        const { user } = get();
        return ['SuperAdmin', 'Admin'].includes(user?.role);
      },

      canManageCameras: () => {
        const { user } = get();
        return ['SuperAdmin', 'Admin'].includes(user?.role);
      },

      getAssignedCameras: () => {
        const { user } = get();
        return user?.assigned_cameras || [];
      },

      getAssignedMenus: () => {
        const { user } = get();
        return user?.assigned_menus || [];
      },

      hasMenuAccess: (menu) => {
        const { user } = get();
        const menus = (user?.assigned_menus || []).map(m => {
          if (m === 'cameras') return 'camera';
          if (m === 'admin') return 'users';
          return m;
        });
        return menus.includes(menu);
      },

      isLicenseExpired: () => {
        const { user } = get();
        if (!user) return false;
        if (user.role !== 'Admin') return false;
        if (!user.license_end_date) return false;
        const endMs = parseLicenseEndMs(user.license_end_date);
        if (endMs === null) return true;
        return endMs < Date.now();
      },
    }),
    {
      name: 'auth-storage', // unique name for localStorage key
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated
      }), // Only persist these fields
    }
  )
);

export default useAuthStore;
