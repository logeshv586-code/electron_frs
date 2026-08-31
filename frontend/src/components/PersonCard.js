import React, { useCallback, useEffect, useState } from 'react';
import AuthenticatedImage from './common/AuthenticatedImage';
import './PersonCard.css';

const PersonCard = ({ name, photoPath, details, viewMode = 'grid' }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  useEffect(() => {
    setImageError(false);
    setImageLoaded(false);
  }, [photoPath]);

  const handleImageError = useCallback(() => {
    setImageError(true);
  }, []);

  const handleImageLoad = useCallback(() => {
    setImageLoaded(true);
  }, []);

  return (
    <div className={`person-card ${viewMode === 'list' ? 'list-view' : ''}`}>
      <div className="photo-container">
        {!imageError && photoPath ? (
          <AuthenticatedImage
            src={photoPath}
            alt={name}
            className={`person-photo ${imageLoaded ? 'loaded' : ''}`}
            onError={handleImageError}
            onLoad={handleImageLoad}
          />
        ) : (
          <div className="no-image" aria-label="Image not available">
            <span>FR</span>
            {viewMode === 'grid' && <span>Image not available</span>}
          </div>
        )}
      </div>

      <div className="card-content-wrapper">
        <div className="card-header">
          <h3 className="person-name">{name}</h3>
        </div>
        <div className="details-container">
          {Object.entries(details || {}).map(([key, value]) => {
            if (!value || ['name', 'photo_path', 'gallery_path'].includes(key)) return null;
            return (
              <div key={key} className="detail-item">
                <span className="detail-label">{key.charAt(0).toUpperCase() + key.slice(1)}:</span>
                <span className="detail-value">{value}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default PersonCard;
