import React from 'react';
import useAuthStore from '../../store/authStore';
import { fixImageUrl } from '../../utils/apiConfig';

const AuthenticatedImage = ({ src, alt = '', onError, onLoad, ...props }) => {
  const token = useAuthStore((state) => state.token);
  const [resolvedSrc, setResolvedSrc] = React.useState(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    let objectUrl = null;
    setFailed(false);
    setResolvedSrc(null);

    if (!src) {
      setFailed(true);
      return () => {};
    }

    const fixedSrc = fixImageUrl(src);
    if (/^(data:|blob:)/i.test(fixedSrc)) {
      setResolvedSrc(fixedSrc);
      return () => {};
    }

    const load = async () => {
      try {
        const response = await fetch(fixedSrc, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`Image request failed (${response.status})`);
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (active) setResolvedSrc(objectUrl);
      } catch (error) {
        if (active) {
          setFailed(true);
          if (onError) onError(error);
        }
      }
    };

    load();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, token, onError]);

  if (failed || !resolvedSrc) return null;
  return <img src={resolvedSrc} alt={alt} onLoad={onLoad} {...props} />;
};

export default AuthenticatedImage;
