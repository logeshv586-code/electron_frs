const NativeWebSocket = window.WebSocket;

const getStoredToken = () => {
  try {
    const persisted = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    return persisted?.state?.token || localStorage.getItem('auth_token') || '';
  } catch (error) {
    return localStorage.getItem('auth_token') || '';
  }
};

if (NativeWebSocket && !window.__FRS_AUTHENTICATED_WEBSOCKET__) {
  function AuthenticatedWebSocket(url, protocols) {
    let target = url;
    try {
      const value = String(url);
      if (value.includes('/ws/recognitions/')) {
        const parsed = new URL(value, window.location.href);
        const token = getStoredToken();
        if (token && !parsed.searchParams.has('token')) parsed.searchParams.set('token', token);
        target = parsed.toString();
      }
    } catch (error) {
      target = url;
    }
    return protocols === undefined
      ? new NativeWebSocket(target)
      : new NativeWebSocket(target, protocols);
  }

  AuthenticatedWebSocket.prototype = NativeWebSocket.prototype;
  ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach((key) => {
    Object.defineProperty(AuthenticatedWebSocket, key, { value: NativeWebSocket[key], enumerable: true });
  });
  window.WebSocket = AuthenticatedWebSocket;
  window.__FRS_AUTHENTICATED_WEBSOCKET__ = true;
}
