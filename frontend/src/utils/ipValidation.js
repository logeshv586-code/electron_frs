/**
 * Extract IP address from stream URL
 * @param {string} streamURL - The RTSP/HTTP stream URL
 * @returns {string|null} - Extracted IP address or null if not found
 */
export function extractIPFromStreamURL(streamURL) {
  if (!streamURL) return null;
  
  // Regular expression to match IPv4 addresses
  const ipPattern = /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/;
  const match = streamURL.match(ipPattern);
  
  return match ? match[1] : null;
}

/**
 * Validate if IP address is within private network ranges
 * @param {string} ip - IP address to validate
 * @returns {object} - Validation result with isValid, type, and message
 */
export function validatePrivateIP(ip) {
  if (!ip) {
    return {
      isValid: false,
      type: 'empty',
      message: 'IP address is required'
    };
  }

  // Validate IP format
  const ipPattern = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
  const match = ip.match(ipPattern);
  
  if (!match) {
    return {
      isValid: false,
      type: 'invalid_format',
      message: 'Invalid IP address format'
    };
  }

  // Check if each octet is valid (0-255)
  const octets = match.slice(1, 5).map(Number);
  if (octets.some(octet => octet < 0 || octet > 255)) {
    return {
      isValid: false,
      type: 'invalid_range',
      message: 'IP address octets must be between 0 and 255'
    };
  }

  // Check if IP is within private ranges
  const [first, second] = octets;
  
  // Private IP ranges:
  // 10.0.0.0 – 10.255.255.255 (Class A)
  // 172.16.0.0 – 172.31.255.255 (Class B)
  // 192.168.0.0 – 192.168.255.255 (Class C)
  
  const isPrivate = (
    first === 10 ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );

  if (!isPrivate) {
    return {
      isValid: false,
      type: 'public_ip',
      message: 'IP address must be within private network ranges:\n• 192.168.0.0 – 192.168.255.255 (most common)\n• 10.0.0.0 – 10.255.255.255\n• 172.16.0.0 – 172.31.255.255'
    };
  }

  return {
    isValid: true,
    type: 'private',
    message: 'Valid private IP address'
  };
}

/**
 * Validate stream URL format
 * @param {string} url - Stream URL to validate
 * @returns {object} - Validation result
 */
export function validateStreamURL(url) {
  if (!url || !url.trim()) {
    return {
      isValid: false,
      message: 'Stream URL is required'
    };
  }

  const trimmedUrl = url.trim();
  
  // Allow local camera indices (0, 1, 2, etc.) for testing
  if (/^\d+$/.test(trimmedUrl)) {
    return {
      isValid: true,
      message: `Valid local camera index: ${trimmedUrl}`,
      isCameraIndex: true
    };
  }
  
  if (!trimmedUrl.startsWith('rtsp://') && !trimmedUrl.startsWith('http://')) {
    return {
      isValid: false,
      message: 'Stream URL must start with rtsp://, http://, or be a camera index (0, 1, 2...)'
    };
  }

  const extractedIP = extractIPFromStreamURL(trimmedUrl);
  if (!extractedIP) {
    return {
      isValid: false,
      message: 'Could not extract IP address from stream URL'
    };
  }

  const ipValidation = validatePrivateIP(extractedIP);
  if (!ipValidation.isValid) {
    return {
      isValid: false,
      message: `Invalid IP address (${extractedIP}): ${ipValidation.message}`
    };
  }

  return {
    isValid: true,
    message: 'Valid stream URL',
    extractedIP
  };
}

/**
 * Format IP validation error message for display
 * @param {object} validation - Validation result from validatePrivateIP
 * @returns {string} - Formatted error message
 */
export function formatIPValidationError(validation) {
  if (validation.isValid) return '';
  
  switch (validation.type) {
    case 'empty':
      return 'Please enter an IP address';
    case 'invalid_format':
      return 'Please enter a valid IP address (e.g., 192.168.1.100)';
    case 'invalid_range':
      return 'IP address octets must be between 0 and 255';
    case 'public_ip':
      return validation.message;
    default:
      return validation.message || 'Invalid IP address';
  }
}
