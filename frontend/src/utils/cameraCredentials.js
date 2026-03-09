// Common camera credentials for different brands
const COMMON_CREDENTIALS = [
  { username: 'admin', password: 'admin' },
  { username: 'admin', password: 'Admin@123' },
  { username: 'admin', password: '123456' },
  { username: 'admin', password: 'password' },
  { username: 'admin', password: '' },
  { username: 'root', password: 'root' },
  { username: 'user', password: 'user' },
  { username: '', password: '' }
];

// Store successful credentials for reuse
const successfulCredentials = new Map();

/**
 * Get the best credentials to try for a camera IP
 * @param {string} cameraIp - Camera IP address
 * @returns {object} - Credentials object with username and password
 */
export const getBestCredentials = (cameraIp) => {
  // First try previously successful credentials for this IP
  if (successfulCredentials.has(cameraIp)) {
    return successfulCredentials.get(cameraIp);
  }
  
  // Otherwise return the first common credential
  return COMMON_CREDENTIALS[0];
};

/**
 * Generate RTSP URL with credentials
 * @param {string} cameraIp - Camera IP address
 * @param {object} credentials - Credentials object
 * @param {number} port - RTSP port (default 554)
 * @param {string} path - RTSP path (default empty)
 * @returns {string} - Complete RTSP URL
 */
export const generateRTSPUrl = (cameraIp, credentials, port = 554, path = '') => {
  const { username, password } = credentials;
  
  let authString = '';
  if (username || password) {
    authString = `${username}:${password}@`;
  }
  
  const pathString = path ? `/${path}` : '';
  return `rtsp://${authString}${cameraIp}:${port}${pathString}`;
};

/**
 * Store successful credentials for future use
 * @param {string} cameraIp - Camera IP address
 * @param {object} credentials - Successful credentials
 */
export const storeSuccessfulCredentials = (cameraIp, credentials) => {
  successfulCredentials.set(cameraIp, credentials);
};

/**
 * Get all common credentials for testing
 * @returns {Array} - Array of credential objects
 */
export const getAllCredentials = () => {
  return [...COMMON_CREDENTIALS];
};

/**
 * Mask credentials in URL for logging
 * @param {string} url - URL with credentials
 * @returns {string} - URL with masked credentials
 */
export const maskCredentials = (url) => {
  try {
    const urlObj = new URL(url);
    if (urlObj.username || urlObj.password) {
      return url.replace(
        `${urlObj.username}:${urlObj.password}@`,
        `${urlObj.username ? '***' : ''}:${urlObj.password ? '***' : ''}@`
      );
    }
    return url;
  } catch (error) {
    return url;
  }
};

/**
 * Extract credentials from RTSP URL
 * @param {string} url - RTSP URL
 * @returns {object} - Extracted credentials and clean URL
 */
export const extractCredentials = (url) => {
  try {
    const urlObj = new URL(url);
    const credentials = {
      username: urlObj.username || '',
      password: urlObj.password || ''
    };
    
    // Create clean URL without credentials
    urlObj.username = '';
    urlObj.password = '';
    const cleanUrl = urlObj.toString();
    
    return { credentials, cleanUrl };
  } catch (error) {
    return {
      credentials: { username: '', password: '' },
      cleanUrl: url
    };
  }
};

export default {
  getBestCredentials,
  generateRTSPUrl,
  storeSuccessfulCredentials,
  getAllCredentials,
  maskCredentials,
  extractCredentials
};
