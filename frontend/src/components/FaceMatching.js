import React, { useState } from 'react';
import axios from 'axios';
import FaceCard from './FaceCard';
import './FaceMatching.css';

import { API_BASE_URL as BASE_URL } from '../utils/apiConfig';
const API_BASE_URL = `${BASE_URL}/api/matching/api/match`;

// Utility function to convert local file paths to API URLs
const convertImagePathToUrl = (imagePath) => {
  if (!imagePath) return '';

  try {
    // Handle Windows path separators
    const normalizedPath = imagePath.replace(/\\/g, '/');

    // Extract person name and image name from the path
    // Expected path format: .../data/person_name/image_name.jpg
    const pathParts = normalizedPath.split('/');
    const dataIndex = pathParts.findIndex(part => part === 'data');

    if (dataIndex !== -1 && pathParts.length > dataIndex + 2) {
      const personName = pathParts[dataIndex + 1];
      const imageName = pathParts[dataIndex + 2];

      // Return the proper API URL for serving gallery images
      const fullUrl = `${BASE_URL}/api/gallery/image/${personName}/${imageName}`;
      // console.log('Converted image path to URL:', fullUrl);
      return fullUrl;
    }

    // Fallback: return empty string if path format is not recognized
    console.warn('Could not parse image path:', imagePath);
    return '';
  } catch (error) {
    console.error('Error converting image path to URL:', error);
    return '';
  }
};

const FaceMatching = () => {
  const [activeTab, setActiveTab] = useState('one-to-many');
  const [selectedImage1, setSelectedImage1] = useState(null);
  const [selectedImage2, setSelectedImage2] = useState(null);
  const [selectedImagePath1, setSelectedImagePath1] = useState('');
  const [selectedImagePath2, setSelectedImagePath2] = useState('');
  const [matchingResults, setMatchingResults] = useState([]);
  const [comparisonResult, setComparisonResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [galleryStats, setGalleryStats] = useState(null);

  const tabs = [
    { id: 'one-to-many', label: 'One-to-Many', icon: '🔍' },
    { id: 'one-to-one', label: 'One-to-One', icon: '⚖️' },
  ];

  const handleImageSelect = (event, imageNumber) => {
    const file = event.target.files[0];
    if (file) {
      if (imageNumber === 1) {
        setSelectedImage1(file);
        setSelectedImagePath1(URL.createObjectURL(file));
      } else {
        setSelectedImage2(file);
        setSelectedImagePath2(URL.createObjectURL(file));
      }
      setMatchingResults([]);
      setComparisonResult(null);
      setError(null);
    }
  };

  const performOneToMany = async () => {
    if (!selectedImage1) {
      setError('Please select an image first.');
      return;
    }

    setLoading(true);
    setError(null);
    setMatchingResults([]);

    try {
      const formData = new FormData();
      formData.append('probe', selectedImage1);

      console.log('Performing one-to-many matching...');
      setError('Processing image... This may take up to 2 minutes for large datasets.');

      const response = await axios.post(`${API_BASE_URL}/one-to-many`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 120000,
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setError(`Uploading image... ${percentCompleted}%`);
        }
      });

      console.log('One-to-many response:', response.data);
      setMatchingResults(response.data.matches || []);
      setError(null);
    } catch (err) {
      console.error('One-to-many matching error:', err);
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  };

  const performOneToOne = async () => {
    if (!selectedImage1 || !selectedImage2) {
      setError('Please select both images to compare.');
      return;
    }

    setLoading(true);
    setError(null);
    setComparisonResult(null);

    try {
      const formData = new FormData();
      formData.append('probe', selectedImage1);
      formData.append('gallery', selectedImage2);

      console.log('Performing one-to-one comparison...');

      const response = await axios.post(`${API_BASE_URL}/one-to-one`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 60000,
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setError(`Uploading images... ${percentCompleted}%`);
        }
      });

      console.log('One-to-one response:', response.data);
      setComparisonResult(response.data);
      setError(null);
    } catch (err) {
      console.error('One-to-one comparison error:', err);
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  };

  const loadGalleryStats = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(`${BASE_URL}/api/matching/api/gallery/stats`);
      console.log('Gallery stats response:', response.data);
      setGalleryStats(response.data);
      setError(null);
    } catch (err) {
      console.error('Gallery stats error:', err);
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  };

  const reloadGallery = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await axios.post(`${BASE_URL}/api/matching/api/gallery/reload`);
      console.log('Gallery reload response:', response.data);
      setError('Gallery reloaded successfully!');

      // Reload stats after successful reload
      setTimeout(() => {
        loadGalleryStats();
      }, 1000);
    } catch (err) {
      console.error('Gallery reload error:', err);
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleApiError = (err) => {
    let errorMessage = 'Operation failed';

    if (err.code === 'ECONNABORTED') {
      errorMessage = 'Request timed out. Please try again.';
    } else if (err.response?.status === 400) {
      errorMessage = err.response.data.detail || 'Invalid request or no face detected';
    } else if (err.response?.status === 500) {
      errorMessage = 'Server error occurred. Please try again.';
    } else if (err.response) {
      errorMessage = `Server error: ${err.response.status} - ${err.response.data?.detail || err.response.statusText}`;
    } else if (err.request) {
      errorMessage = 'Cannot connect to backend server. Please ensure the server is running.';
    } else {
      errorMessage = `Error: ${err.message}`;
    }

    setError(errorMessage);
  };

  const renderOneToMany = () => (
    <div className="matching-content">
      <div className="image-section">
        <h3>Upload Image to Find Matches</h3>
        <div className="upload-container one-to-many-upload" style={{ display: 'flex', justifyContent: 'center' }}>
          <div className="image-upload" style={{ width: '220px', maxWidth: '220px', flexShrink: 0, flexGrow: 0 }}>
            {selectedImagePath1 ? (
              <img src={selectedImagePath1} alt="Selected" className="preview-image" />
            ) : (
              <div className="image-placeholder">
                <span>📷</span>
                <p>Select an image to find Known matches</p>
              </div>
            )}
            <input
              type="file"
              accept="image/*"
              onChange={(e) => handleImageSelect(e, 1)}
              className="file-input"
              id="image-input-1"
            />
            <label htmlFor="image-input-1" className="upload-btn">
              Select Image
            </label>
          </div>
        </div>
        <button
          onClick={performOneToMany}
          disabled={!selectedImage1 || loading}
          className="action-btn primary"
        >
          {loading ? 'Searching...' : 'Find Matches'}
        </button>
      </div>

      <div className="results-section">
        {loading ? (
          <div className="loading">Searching for matches...</div>
        ) : matchingResults.length > 0 ? (
          <div>
            <h3>Matching Results ({matchingResults.length} found)</h3>
            <div className="results-grid">
              {matchingResults.map((match, index) => (
                <div key={index} className="match-result">
                  <FaceCard
                    imagePath={convertImagePathToUrl(match.match_details?.image_path || '')}
                    name={match.person_name || 'Unknown'}
                    camera={''}
                    timestamp={''}
                  />
                  <div className="match-confidence">
                    Confidence: {(match.confidence || 0).toFixed(1)}%
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : selectedImage1 && !loading ? (
          <div className="empty-state">
            No matching faces found
          </div>
        ) : null}
      </div>
    </div>
  );

  const renderOneToOne = () => (
    <div className="matching-content">
      <div className="comparison-section">
        <h3>Compare Two Face Images</h3>
        <div className="images-container">
          <div className="image-upload">
            <h4>First Image</h4>
            {selectedImagePath1 ? (
              <img src={selectedImagePath1} alt="First" className="preview-image" />
            ) : (
              <div className="image-placeholder">
                <span>📷</span>
                <p>Select first image</p>
              </div>
            )}
            <input
              type="file"
              accept="image/*"
              onChange={(e) => handleImageSelect(e, 1)}
              className="file-input"
              id="image-input-comp-1"
            />
            <label htmlFor="image-input-comp-1" className="upload-btn">
              Select First Image
            </label>
          </div>

          <div className="vs-divider">VS</div>

          <div className="image-upload">
            <h4>Second Image</h4>
            {selectedImagePath2 ? (
              <img src={selectedImagePath2} alt="Second" className="preview-image" />
            ) : (
              <div className="image-placeholder">
                <span>📷</span>
                <p>Select second image</p>
              </div>
            )}
            <input
              type="file"
              accept="image/*"
              onChange={(e) => handleImageSelect(e, 2)}
              className="file-input"
              id="image-input-comp-2"
            />
            <label htmlFor="image-input-comp-2" className="upload-btn">
              Select Second Image
            </label>
          </div>
        </div>

        <button
          onClick={performOneToOne}
          disabled={!selectedImage1 || !selectedImage2 || loading}
          className="action-btn primary"
        >
          {loading ? 'Comparing...' : 'Compare Faces'}
        </button>
      </div>

      {comparisonResult && (
        <div className="comparison-result">
          <h3>Comparison Result</h3>
          <div className="result-card">
            <div className="similarity-score">
              <span className="score-label">Similarity Score:</span>
              <span className={`score-value ${comparisonResult.confidence > 70 ? 'high' : comparisonResult.confidence > 40 ? 'medium' : 'low'}`}>
                {(comparisonResult.confidence || 0).toFixed(1)}%
              </span>
            </div>
            <div className="match-status">
              <span className="status-label">Match Status:</span>
              <span className={`status-value ${comparisonResult.is_match ? 'match' : 'no-match'}`}>
                {comparisonResult.is_match ? '✅ Match' : '❌ No Match'}
              </span>
            </div>
            {comparisonResult.face_distance && (
              <div className="distance-info">
                <span className="distance-label">Face Distance:</span>
                <span className="distance-value">{comparisonResult.face_distance.toFixed(4)}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  const renderGalleryStats = () => (
    <div className="matching-content">
      <div className="stats-section">
        <div className="stats-header">
          <h3>Gallery Statistics</h3>
          <div className="stats-actions">
            <button onClick={loadGalleryStats} className="action-btn secondary">
              Refresh Stats
            </button>
            <button onClick={reloadGallery} className="action-btn primary">
              Reload Gallery
            </button>
          </div>
        </div>

        {galleryStats ? (
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-value">{galleryStats.total_images || 0}</div>
              <div className="stat-label">Total Images</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{galleryStats.unique_persons || 0}</div>
              <div className="stat-label">Unique Persons</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{Object.keys(galleryStats.person_counts || {}).length}</div>
              <div className="stat-label">Person Categories</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{new Date().toLocaleDateString()}</div>
              <div className="stat-label">Last Checked</div>
            </div>
          </div>
        ) : (
          <div className="stats-placeholder">
            <p>Click "Refresh Stats" to load gallery statistics</p>
          </div>
        )}
      </div>
    </div>
  );

  const renderActiveContent = () => {
    switch (activeTab) {
      case 'one-to-many':
        return renderOneToMany();
      case 'one-to-one':
        return renderOneToOne();
      case 'gallery-stats':
        return renderGalleryStats();
      default:
        return renderOneToMany();
    }
  };

  return (
    <div className="face-matching">
      <div className="matching-header">
        <h2>Face Matching System</h2>
        <div className="matching-tabs">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="tab-icon">{tab.icon}</span>
              <span className="tab-text">{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className={`status-message ${error.includes('successfully') ? 'success' : 'error'}`}>
          {error}
        </div>
      )}

      {renderActiveContent()}
    </div>
  );
};

export default FaceMatching;