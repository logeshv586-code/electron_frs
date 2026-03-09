/**
 * Parse stream URL to extract collection name and camera IP
 * @param {string} streamUrl - The stream URL to parse
 * @returns {object} - Object containing collectionName and cameraIp
 */
export const parseStreamUrl = (streamUrl) => {
  try {
    const url = new URL(streamUrl);
    const pathParts = url.pathname.split('/').filter(part => part);
    
    // Assuming URL format like: /stream/collection_name/camera_ip
    if (pathParts.length >= 3 && pathParts[0] === 'stream') {
      return {
        collectionName: pathParts[1],
        cameraIp: pathParts[2]
      };
    }
    
    // Fallback: try to extract IP from hostname
    const hostname = url.hostname;
    if (hostname && hostname !== '192.168.1.209') {
      return {
        collectionName: 'default',
        cameraIp: hostname
      };
    }
    
    return {
      collectionName: null,
      cameraIp: null
    };
  } catch (error) {
    console.error('Error parsing stream URL:', error);
    return {
      collectionName: null,
      cameraIp: null
    };
  }
};

/**
 * Generate a unique camera ID based on collection and IP
 * @param {string} collectionName - Collection name
 * @param {string} cameraIp - Camera IP address
 * @returns {string} - Generated camera ID
 */
export const generateCameraId = (collectionName, cameraIp) => {
  if (!collectionName || !cameraIp) {
    return `camera_${Date.now()}`;
  }
  return `${collectionName}_${cameraIp}`.replace(/[^a-zA-Z0-9_]/g, '_');
};

/**
 * Validate camera configuration
 * @param {object} config - Camera configuration object
 * @returns {object} - Validation result
 */
export const validateCameraConfig = (config) => {
  const errors = [];
  
  if (!config.name || config.name.trim().length === 0) {
    errors.push('Camera name is required');
  }
  
  if (!config.rtsp_url || config.rtsp_url.trim().length === 0) {
    errors.push('RTSP URL is required');
  }
  
  if (config.rtsp_url && !config.rtsp_url.startsWith('rtsp://')) {
    errors.push('RTSP URL must start with rtsp://');
  }
  
  return {
    isValid: errors.length === 0,
    errors
  };
};

/**
 * Format camera display name
 * @param {object} camera - Camera object
 * @returns {string} - Formatted display name
 */
export const formatCameraDisplayName = (camera) => {
  if (!camera) return 'Unknown Camera';
  
  if (camera.name && camera.name.trim()) {
    return camera.name.trim();
  }
  
  if (camera.ip) {
    return `Camera ${camera.ip}`;
  }
  
  return `Camera ${camera.id || 'Unknown'}`;
};

export default {
  parseStreamUrl,
  generateCameraId,
  validateCameraConfig,
  formatCameraDisplayName
};
