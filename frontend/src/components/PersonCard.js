import React, { useState, useEffect } from 'react';
import { fixImageUrl } from '../utils/apiConfig';
import './PersonCard.css';

const PersonCard = ({ name, photoPath, details, viewMode = 'grid' }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const fixedPhotoPath = fixImageUrl(photoPath);

  const handleImageError = (event) => {
    // Only log error if it's not a 404 (missing image)
    if (event?.target?.src) {
      // Check if it's a 404 by trying to fetch the image
      fetch(event.target.src, { method: 'HEAD' })
        .then(response => {
          if (response.status === 404) {
            // console.warn(`Image not found for ${name}:`, fixedPhotoPath);
          } else {
            // console.error('Failed to load image:', fixedPhotoPath);
          }
        })
        .catch(() => {
          // console.warn(`Image not accessible for ${name}:`, fixedPhotoPath);
        });
    }
    setImageError(true);
  };

  const handleImageLoad = () => {
    // console.log('Image loaded successfully:', fixedPhotoPath);
    setImageLoaded(true);
  };

  // Reset image states when photoPath changes
  useEffect(() => {
    setImageError(false);
    setImageLoaded(false);
  }, [fixedPhotoPath]);

  return (
    <div className={`person-card ${viewMode === 'list' ? 'list-view' : ''}`}>
      <div className="photo-container">
        {!imageError ? (
          <img
            src={fixedPhotoPath}
            alt={name}
            className={`person-photo ${imageLoaded ? 'loaded' : ''}`}
            onError={handleImageError}
            onLoad={handleImageLoad}
          />
        ) : (
          <div className="no-image">
            <span>📷</span>
            {viewMode === 'grid' && <span>Image Not Available</span>}
          </div>
        )}
      </div>
      
      <div className="card-content-wrapper">
        <div className="card-header">
          <h3 className="person-name">{name}</h3>
        </div>

        <div className="details-container">
          {Object.entries(details).map(([key, value]) => {
            if (value && key !== 'name' && key !== 'photo_path' && key !== 'gallery_path') {
              return (
                <div key={key} className="detail-item">
                  <span className="detail-label">{key.charAt(0).toUpperCase() + key.slice(1)}:</span>
                  <span className="detail-value">{value}</span>
                </div>
              );
            }
            return null;
          })}
        </div>
      </div>
    </div>
  );
};

export default PersonCard;
