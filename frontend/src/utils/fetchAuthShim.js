import axios from 'axios';

// Global fetch shim to inject auth token
(function() {
  const originalFetch = window.fetch;
  
  window.fetch = async function(...args) {
    const [url, options = {}] = args;
    
    // Get auth token from localStorage
    const token = localStorage.getItem('auth_token');
    
    if (token && url.includes('/api/')) {
      // Clone options to avoid modifying the original
      const modifiedOptions = {
        ...options,
        headers: {
          ...options.headers,
          'Authorization': `Bearer ${token}`,
        },
      };
      
      return originalFetch(url, modifiedOptions);
    }
    
    return originalFetch(...args);
  };
})();

// Axios interceptor for auth token injection
axios.interceptors.request.use(
  function(config) {
    const token = localStorage.getItem('auth_token');
    const url = config?.url || '';
    if (token && url.includes('/api/')) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  function(error) {
    return Promise.reject(error);
  }
);

axios.interceptors.response.use(
  function(response) {
    return response;
  },
  function(error) {
    if (error?.response?.status === 401) {
      localStorage.removeItem('auth_token');
      console.warn('Authentication token invalid, please login again');
    }
    return Promise.reject(error);
  }
);

// Export helper functions for manual API calls
export const apiRequest = async (url, options = {}) => {
  const token = localStorage.getItem('auth_token');
  
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  
  if (token && url.includes('/api/')) {
    headers.Authorization = `Bearer ${token}`;
  }
  
  const response = await fetch(url, {
    ...options,
    headers,
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return response.json();
};

export const getAuthHeaders = () => {
  const token = localStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};
