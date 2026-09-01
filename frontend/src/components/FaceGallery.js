import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Grid, List as ListIcon, RefreshCw, Search, Users, UserCheck, Briefcase, Clock } from 'lucide-react';
import useAuthStore from '../store/authStore';
import PersonCard from './PersonCard';
import { API_BASE_URL } from '../utils/apiConfig';
import './FaceGallery.css';

const FaceGallery = () => {
  const token = useAuthStore((state) => state.token);
  const [galleryData, setGalleryData] = useState({});
  const [backendStats, setBackendStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All Categories');
  const [viewMode, setViewMode] = useState('grid');

  const authConfig = useMemo(() => ({
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    timeout: 10000,
  }), [token]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    const params = { t: Date.now() };
    if (searchQuery.trim()) params.name = searchQuery.trim();
    if (selectedCategory !== 'All Categories') params.category = selectedCategory;
    try {
      const [galleryResponse, statsResponse] = await Promise.all([
        axios.get(`${API_BASE_URL}/api/registration/gallery`, { ...authConfig, params }),
        axios.get(`${API_BASE_URL}/api/registration/metadata/statistics`, { ...authConfig, params: { t: Date.now() } }),
      ]);
      setGalleryData(galleryResponse.data || {});
      setBackendStats(statsResponse.data || null);
    } catch (requestError) {
      const status = requestError.response?.status;
      setError(status === 401 || status === 403 ? 'You do not have access to this biometric gallery.' : 'Could not load the face gallery.');
    } finally {
      setLoading(false);
    }
  }, [authConfig, searchQuery, selectedCategory]);

  useEffect(() => { loadData(); }, [loadData]);

  const computedStats = useMemo(() => {
    const values = Object.values(galleryData || {});
    const categories = {};
    let registeredToday = 0;
    const today = new Date().toISOString().slice(0, 10);
    values.forEach((person) => {
      const category = person.category || 'Other';
      categories[category] = (categories[category] || 0) + 1;
      if (String(person.registration_date || '').startsWith(today)) registeredToday += 1;
    });
    return {
      total_registered: values.length,
      registered_today: registeredToday,
      categories,
    };
  }, [galleryData]);

  const categories = useMemo(() => {
    const source = backendStats?.categories || computedStats.categories || {};
    return ['All Categories', ...Object.keys(source).filter(Boolean)];
  }, [backendStats, computedStats]);

  const totalCategorized = Object.values(computedStats.categories).reduce((sum, count) => sum + Number(count || 0), 0);
  const entries = Object.entries(galleryData || {});

  return (
    <div className="gallery-container product-surface-page">
      <div className="gallery-header product-page-header">
        <div className="header-content">
          <h2>Face Gallery</h2>
          <p>Registered employee identities and approved enrollment images.</p>
        </div>
        <div className="gallery-controls-area compact-toolbar">
          <div className="search-box">
            <Search size={15} />
            <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search employees" onKeyDown={(event) => event.key === 'Enter' && loadData()} />
          </div>
          <select className="filter-select" value={selectedCategory} onChange={(event) => setSelectedCategory(event.target.value)}>
            {categories.map((category) => <option key={category} value={category}>{category}</option>)}
          </select>
          <div className="view-toggles">
            <button className={`view-btn ${viewMode === 'grid' ? 'active' : ''}`} onClick={() => setViewMode('grid')} title="Grid view"><Grid size={15} /></button>
            <button className={`view-btn ${viewMode === 'list' ? 'active' : ''}`} onClick={() => setViewMode('list')} title="List view"><ListIcon size={15} /></button>
          </div>
          <button className="refresh-btn" onClick={loadData} disabled={loading}><RefreshCw size={14} /> Refresh</button>
        </div>
      </div>

      <div className="stats-grid compact-stats-grid">
        <div className="stat-card"><span className="stat-icon blue"><Users size={18} /></span><div className="stat-info"><h3>{computedStats.total_registered}</h3><p>Registered</p></div></div>
        <div className="stat-card"><span className="stat-icon green"><UserCheck size={18} /></span><div className="stat-info"><h3>{entries.length}</h3><p>Loaded profiles</p></div></div>
        <div className="stat-card"><span className="stat-icon orange"><Briefcase size={18} /></span><div className="stat-info"><h3>{totalCategorized}</h3><p>Categorized</p></div></div>
        <div className="stat-card"><span className="stat-icon gray"><Clock size={18} /></span><div className="stat-info"><h3>{computedStats.registered_today}</h3><p>Added today</p></div></div>
      </div>

      {error && <div className="error-message gallery-error">{error}</div>}

      {loading ? (
        <div className="empty-state"><div className="loading-spinner" /><p>Loading biometric profiles...</p></div>
      ) : entries.length === 0 ? (
        <div className="empty-state"><p>No registered faces match the current filters.</p></div>
      ) : (
        <>
          <div className="section-title">Registered persons <span className="count-badge">{entries.length}</span></div>
          <div className={`gallery-grid ${viewMode === 'list' ? 'list-mode' : ''}`}>
            {entries.map(([personId, person]) => {
              const imageFilename = person.image_filename || 'original.jpg';
              const imageUrl = person.image_url
                ? `${API_BASE_URL}${person.image_url}`
                : `${API_BASE_URL}/api/gallery/image/${person.company_id || 'default'}/${personId}/${imageFilename}`;
              return (
                <PersonCard
                  key={personId}
                  name={person.name || personId}
                  photoPath={imageUrl}
                  details={{
                    employee_id: person.emp_id,
                    department: person.department,
                    category: person.category,
                    age: person.age_range && person.age_range !== 'N/A' ? person.age_range : person.age,
                    gender: person.gender,
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
