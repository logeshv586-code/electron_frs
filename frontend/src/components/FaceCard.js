import React, { useState, useEffect, useRef } from 'react';
import { Grid } from 'lucide-react';
import { fixImageUrl } from '../utils/apiConfig';
import './FaceCard.css';

const FaceCard = ({ imagePath, name, camera, timestamp }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const imageRef = useRef(null);
  const fixedImagePath = fixImageUrl(imagePath);

  const handleImageError = () => {
    console.error('Failed to load image:', fixedImagePath);
    setImageError(true);
  };

  const handleImageLoad = () => {
    setImageLoaded(true);
  };

  useEffect(() => {
    setImageError(false);
    if (imageRef.current && imageRef.current.complete && imageRef.current.naturalWidth > 0) {
      setImageLoaded(true);
    } else {
      setImageLoaded(false);
    }
  }, [fixedImagePath]);

  // Format timestamp for display
  const formatTimestamp = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
    } catch (error) {
      return timestamp;
    }
  };

  const handleFaceCapture = (e) => {
    e.stopPropagation();
    // Face capture logic placeholder
    console.log("Face capture triggered for", fixedImagePath);
  };

  return (
    <div className="face-card">
      <div className="image-container">
        {!imageError ? (
          <img
            ref={imageRef}
            src={fixedImagePath}
            alt={name}
            className={`face-image ${imageLoaded ? 'loaded' : ''}`}
            onError={handleImageError}
            onLoad={handleImageLoad}
          />
        ) : (
          <div className="no-image">
            <span>No Image Available</span>
            <small>{fixedImagePath}</small>
          </div>
        )}
      </div>

      <div className="face-info">
        <h4 className="face-name">{name}</h4>
        {camera && <p className="face-camera">Camera: {camera}</p>}
        {timestamp && <p className="face-timestamp">{formatTimestamp(timestamp)}</p>}
      </div>
    </div>
  );
};

export default FaceCard;
