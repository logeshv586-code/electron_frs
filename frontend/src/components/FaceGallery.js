import React, { useState, useEffect, useCallback } from 'react';
import useAuthStore from '../store/authStore';
import axios from 'axios';
import { Search, Grid, List as ListIcon, RefreshCw, Users, UserCheck, Briefcase, Clock } from 'lucide-react';
import PersonCard from './PersonCard';
import './FaceGallery.css';

import { API_BASE_URL } from '../utils/apiConfig';

const GALLERY_ENDPOINT = `${API_BASE_URL}/api/registration/gallery`;
const STATS_ENDPOINT = `${API_BASE_URL}/api/registration/metadata/statistics`;

const FaceGallery = () => {
  const { user: currentUser } = useAuthStore();
  const [galleryData, setGalleryData] = useState({});
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [columns, setColumns] = useState(4);

  // Filter States
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All Categories');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' or 'list'

  const calculateColumns = useCallback(() => {
    const containerWidth = window.innerWidth - 80; // Account for margins
    const minCardWidth = 250;
    const spacing = 20;
    const maxCols = Math.max(1, Math.floor((containerWidth + spacing) / (minCardWidth + spacing)));
    return Math.min(maxCols, 5);
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Prepare query params
      const params = {};
      if (searchQuery.trim()) params.name = searchQuery;
      if (selectedCategory !== 'All Categories') params.category = selectedCategory;

      // Add timestamp to prevent caching
      const timestamp = new Date().getTime();

      const [galleryRes, statsRes] = await Promise.all([
        axios.get(`${GALLERY_ENDPOINT}?t=${timestamp}`, { params, timeout: 10000 }),
        axios.get(`${STATS_ENDPOINT}?t=${timestamp}`, { timeout: 5000 })
      ]);

      setGalleryData(galleryRes.data);
      setStats(statsRes.data);
    } catch (err) {
      console.error('Data loading error:', err);
      let errorMessage = 'Failed to load gallery data';
      if (err.response) {
        errorMessage = `Server error: ${err.response.status}`;
      } else if (err.request) {
        errorMessage = 'Cannot connect to backend server';
      }
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, selectedCategory]);

  // Initial load and focus handler
  useEffect(() => {
    loadData();

    // Refresh when window gains focus (useful when returning from other tabs)
    const handleFocus = () => loadData();
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, [loadData]);

  // Handle Resize
  useEffect(() => {
    const handleResize = () => setColumns(calculateColumns());
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [calculateColumns]);

  // Compute stats from galleryData directly for robustness
  const computedStats = React.useMemo(() => {
    if (!galleryData) return null;

    const cats = {};
    let todayCount = 0;
    const todayStr = new Date().toISOString().split('T')[0];

    Object.values(galleryData).forEach(person => {
      // Categories
      const cat = (person.category || 'unknown').toLowerCase();
      cats[cat] = (cats[cat] || 0) + 1;

      // Registered Today
      if (person.registration_date && person.registration_date.startsWith(todayStr)) {
        todayCount++;
      }
    });

    return {
      categories: cats,
      registered_today: todayCount,
      total_registered: Object.keys(galleryData).length
    };
  }, [galleryData]);

  // Use computed stats or backend stats (prefer computed for consistency with view)
  const displayStats = computedStats || stats || { categories: {}, registered_today: 0, total_registered: 0 };

  const [availableCategories, setAvailableCategories] = useState(['All Categories']);

  // Update available categories only when viewing all data (no filters)
  useEffect(() => {
    // If we have stats from backend, use those (preferred)
    if (stats && stats.categories && Object.keys(stats.categories).length > 0) {
      const cats = ['All Categories'];
      Object.keys(stats.categories).forEach(cat => {
        if (!cats.includes(cat)) cats.push(cat);
      });
      setAvailableCategories(cats);
    }
    // Fallback: If backend stats are empty (e.g. server issue), derive from full gallery data
    else if (computedStats && searchQuery === '' && selectedCategory === 'All Categories') {
      const cats = ['All Categories'];
      Object.keys(computedStats.categories).forEach(cat => {
        if (!cats.includes(cat)) cats.push(cat);
      });
      setAvailableCategories(cats);
    }
  }, [stats, computedStats, searchQuery, selectedCategory]);

  // Format category for display
  const getDisplayCategory = (cat) => {
    if (cat === 'All Categories') return 'All Categories';
    return cat.split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  // Format date
  const formatDate = (isoString) => {
    if (!isoString) return 'Never';
    const date = new Date(isoString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="gallery-container">
      {/* Header */}
      <div className="gallery-header">
        <div className="header-content">
          <h2>Face Gallery</h2>
          <p>Registered identities with biometric and profile data</p>
        </div>

        <div className="gallery-controls-area">
          <div className="status-badge">
            <div className="status-dot"></div>
            <span>{Object.keys(galleryData).length} faces loaded</span>
          </div>

          <div className="search-box">
            <Search size={18} className="search-icon" />
            <input
              type="text"
              className="search-input"
              placeholder="Search by name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadData()}
            />
          </div>

          <select
            className="filter-select"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
          >
            {availableCategories.map(cat => (
              <option key={cat} value={cat}>{getDisplayCategory(cat)}</option>
            ))}
          </select>

          <div className="view-toggles">
            <button
              className={`view-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
            >
              <Grid size={18} />
            </button>
            <button
              className={`view-btn ${viewMode === 'list' ? 'active' : ''}`}
              onClick={() => setViewMode('list')}
            >
              <ListIcon size={18} />
            </button>
          </div>

          <button onClick={loadData} className="refresh-btn">
            <RefreshCw size={18} />
            Refresh Gallery
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {displayStats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-icon blue">
              <Users size={24} />
            </div>
            <div className="stat-info">
              <h3>{displayStats.total_registered}</h3>
              <p>Total Registered</p>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon green">
              <UserCheck size={24} />
            </div>
            <div className="stat-info">
              <h3>{Object.keys(galleryData).length}</h3>
              <p>Active Profiles</p>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon orange">
              <Briefcase size={24} />
            </div>
            <div className="stat-info">
              <h3>
                {selectedCategory === 'All Categories'
                  ? Object.values(displayStats.categories || {}).reduce((a, b) => a + b, 0)
                  : (displayStats.categories && displayStats.categories[selectedCategory.toLowerCase()]) || 0
                }
              </h3>
              <p>{selectedCategory === 'All Categories' ? 'Total Categorized' : getDisplayCategory(selectedCategory)}</p>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon gray">
              <Clock size={24} />
            </div>
            <div className="stat-info">
              <h3>{displayStats.registered_today || 0}</h3>
              <p>Registered Today</p>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="empty-state">
          <div className="loading-spinner"></div>
          <p>Loading gallery data...</p>
        </div>
      ) : error ? (
        <div className="empty-state" style={{ borderColor: '#ef4444', color: '#ef4444' }}>
          <p>{error}</p>
          <button onClick={loadData} className="refresh-btn" style={{ marginTop: '16px' }}>
            Try Again
          </button>
        </div>
      ) : Object.keys(galleryData).length === 0 ? (
        <div className="empty-state">
          <p>No faces found matching your criteria.</p>
        </div>
      ) : (
        <>
          <div className="section-title">
            Registered Persons <span className="count-badge">{Object.keys(galleryData).length} records</span>
          </div>

          <div
            className="gallery-grid"
            style={{
              gridTemplateColumns: viewMode === 'grid' ? `repeat(${columns}, 1fr)` : '1fr',
              gap: '20px'
            }}
          >
            {Object.entries(galleryData).map(([personId, personData]) => {
              const imageFilename = personData.image_filename || 'original.jpg';
              return (
                <PersonCard
                  key={personId}
                  name={personData.name}
                   photoPath={personData.image_url ? `${API_BASE_URL}${personData.image_url}` : `${API_BASE_URL}/api/gallery/image/${personData.company_id || 'default'}/${personId}/${imageFilename}`}
                  details={{
                    age: (personData.age_range && personData.age_range !== 'N/A') ? personData.age_range : personData.age,
                    gender: personData.gender,
                    category: personData.category
                  }}
                  viewMode={viewMode}
                />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

export default FaceGallery;
