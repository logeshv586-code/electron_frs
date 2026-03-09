// Smart API URL detection: defaults to 192.168.1.209, can be overridden
// Priority: 1. Environment variable, 2. 192.168.1.209 (for local dev), 3. Server IP (fallback)
const getApiBaseUrl = () => {
  // If explicitly set via environment variable, use it
  if (process.env.REACT_APP_API_BASE_URL) {
    return process.env.REACT_APP_API_BASE_URL;
  }

  // Check for saved preference
  const savedUrl = localStorage.getItem('api_base_url');
  if (savedUrl) {
    return savedUrl;
  }

  // Smart default: use current hostname
  // This allows the app to work on both localhost and when accessed via IP
  const hostname = window.location.hostname;
  return `http://${hostname}:8005`;
};

export const API_BASE_URL = getApiBaseUrl();

export const getAugmentUrl = (endpoint = '') => {
  const base = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;
  return endpoint ? `${base}/${endpoint}` : base;
};

export const getApiUrl = (endpoint) => {
  return `${API_BASE_URL}${endpoint}`;
};

export const fixImageUrl = (url) => {
  if (!url) return '';
  const currentApiUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;

  // Handle relative paths from the backend
  if (url.startsWith('/')) {
    return `${currentApiUrl}${url}`;
  }

  // Handle explicit localhost URLs (legacy fallback)
  if (url.includes('localhost')) {
    return url.replace(/http:\/\/localhost:\d+/, currentApiUrl);
  }

  return url;
};

// Helper to detect which backend is available (for auto-detection if needed)
export const detectBackendUrl = async () => {
  const hostname = window.location.hostname;
  const savedUrl = localStorage.getItem('api_base_url');

  // Prioritize the current hostname, then saved URL, then try common fallbacks
  const urls = [
    `http://${hostname}:8005`,
    savedUrl,
    'http://localhost:8005',
    'http://127.0.0.1:8005',
    'http://192.168.1.209:8005'
  ].filter(url => url); // Remove null/undefined

  // Remove duplicates
  const uniqueUrls = [...new Set(urls)];

  for (const url of uniqueUrls) {
    try {
      const response = await fetch(`${url}/api/status`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000) // 5 second timeout
      });
      if (response.ok) {
        return url;
      }
    } catch (error) {
      // Try next URL
      continue;
    }
  }

  // Return null if none found, let caller decide or fallback to current
  return null;
};

export default {
  API_BASE_URL,
  getAugmentUrl,
  getApiUrl,
  fixImageUrl,
  detectBackendUrl
};
