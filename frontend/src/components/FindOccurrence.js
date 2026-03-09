import React, { useState } from 'react';
import axios from 'axios';
import { Search, Upload, Image as ImageIcon, X, AlertCircle, Loader } from 'lucide-react';
import FaceCard from './FaceCard';
import './FindOccurrence.css';

import { API_BASE_URL as BASE_URL } from '../utils/apiConfig';
const API_BASE_URL = `${BASE_URL}/api/events`;

const FindOccurrence = () => {
  const [selectedImage, setSelectedImage] = useState(null);
  const [selectedImagePath, setSelectedImagePath] = useState('');
  const [matchingFaces, setMatchingFaces] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchMode, setSearchMode] = useState('known'); // 'known' or 'unknown'

  const handleImageSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      setSelectedImage(file);
      setSelectedImagePath(URL.createObjectURL(file));
      setMatchingFaces([]);
      setError(null);
    }
  };

  const clearImage = () => {
    setSelectedImage(null);
    setSelectedImagePath('');
    setMatchingFaces([]);
    setError(null);
  };

  const findMatches = async (mode = 'known', retryCount = 0) => {
    if (!selectedImage) {
      setError('Please select an image first.');
      return;
    }

    setLoading(true);
    setError(null);
    setMatchingFaces([]);
    setSearchMode(mode);

    try {
      const formData = new FormData();
      formData.append('image', selectedImage);

      const endpoint = mode === 'known' ? '/match-face' : '/match-face-unknown';
      console.log(`Finding ${mode} matches for image:`, selectedImage.name);
      
      const response = await axios.post(`${API_BASE_URL}${endpoint}`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 120000, // 2 minutes
        onUploadProgress: (progressEvent) => {
          // Optional: handle progress
        }
      });

      console.log('Match response:', response.data);
      setMatchingFaces(response.data);
      setError(null);
    } catch (err) {
      console.error('Find matches error:', err);
      let errorMessage = 'Failed to find matches';

      if (err.code === 'ECONNABORTED') {
        if (retryCount < 2) {
          setError(`Request timed out. Retrying... (${retryCount + 1}/3)`);
          setTimeout(() => findMatches(mode, retryCount + 1), 2000);
          return;
        } else {
          errorMessage = 'Request timed out. The dataset might be very large.';
        }
      } else if (err.response?.status === 400) {
        errorMessage = err.response.data.detail || 'Invalid image or no face detected';
      } else {
        errorMessage = `Error: ${err.message}`;
      }

      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="find-occurrence-page">
      {/* Search Card */}
      <div className="search-card">
        <div className="search-header">
          <div className="icon-box">
            <Search size={20} />
          </div>
          <div className="title-group">
            <h3>Image Search</h3>
            <p>Upload an image to find occurrences in video history</p>
          </div>
        </div>

        <div className="search-content">
          <div className="image-upload-area">
            {selectedImagePath ? (
              <div className="preview-container">
                <img src={selectedImagePath} alt="Selected" className="preview-image" />
                <button className="btn-remove-image" onClick={clearImage}>
                  <X size={16} />
                </button>
              </div>
            ) : (
              <label className="upload-placeholder">
                <input
                  type="file"
                  accept="image/*"
                  onChange={handleImageSelect}
                  className="hidden-input"
                />
                <div className="upload-icon">
                  <Upload size={24} />
                </div>
                <span>Click to upload or drag image here</span>
                <span className="upload-hint">Supports JPG, PNG</span>
              </label>
            )}
          </div>

          <div className="search-actions">
            <button 
              className={`btn-search-action ${searchMode === 'known' ? 'primary' : 'secondary'}`}
              onClick={() => findMatches('known')}
              disabled={!selectedImage || loading}
            >
              {loading && searchMode === 'known' ? <Loader size={16} className="spin" /> : <Search size={16} />}
              Find Known Matches
            </button>
            
            <button 
              className={`btn-search-action ${searchMode === 'unknown' ? 'primary' : 'secondary'}`}
              onClick={() => findMatches('unknown')}
              disabled={!selectedImage || loading}
            >
              {loading && searchMode === 'unknown' ? <Loader size={16} className="spin" /> : <AlertCircle size={16} />}
              Find Unknown Matches
            </button>
          </div>
        </div>
        
        {error && (
          <div className="error-banner">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Results Card */}
      <div className="results-card">
        <div className="results-header">
          <div className="header-left">
            <div className="icon-box secondary">
              <ImageIcon size={20} />
            </div>
            <div className="title-group">
              <h3>Search Results</h3>
              <span className="count">{matchingFaces.length} matches found</span>
            </div>
          </div>
        </div>

        <div className="results-content">
          {loading ? (
            <div className="state-container">
              <div className="spinner"></div>
              <p>Searching database...</p>
            </div>
          ) : matchingFaces.length > 0 ? (
            <div className="faces-grid">
              {matchingFaces.map((match, index) => (
                <FaceCard
                  key={`match-${index}`}
                  imagePath={match.image_path}
                  name={`${match.name}`}
                  confidence={match.confidence}
                  camera={match.camera || "Unknown Camera"}
                  timestamp={match.timestamp}
                />
              ))}
            </div>
          ) : selectedImage ? (
            <div className="state-container">
              <div className="empty-icon">🔍</div>
              <p>No matching faces found</p>
            </div>
          ) : (
            <div className="state-container">
              <div className="empty-icon">👆</div>
              <p>Upload an image to start searching</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default FindOccurrence;
