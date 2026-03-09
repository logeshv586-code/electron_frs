import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import DatePicker from 'react-datepicker';
import { format, subDays, differenceInDays } from 'date-fns';
import {
  Search,
  X,
  Download,
  List,
  Grid,
  Calendar,
  Filter,
  User,
  Camera,
  ChevronDown
} from 'lucide-react';
import FaceCard from './FaceCard';
import "react-datepicker/dist/react-datepicker.css";
import './FaceEvents.css';

import { API_BASE_URL as BASE_URL, fixImageUrl } from '../utils/apiConfig';
const API_BASE_URL = `${BASE_URL}/api/events`;

const FaceEvents = () => {
  // Filter States
  const [cameras, setCameras] = useState(['All Cameras']);
  const [selectedCamera, setSelectedCamera] = useState('All Cameras');
  const [nameFilter, setNameFilter] = useState('');
  const [fromDate, setFromDate] = useState(null);
  const [toDate, setToDate] = useState(null);

  // Data States
  const [faces, setFaces] = useState([]);
  const [activeTab, setActiveTab] = useState('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'grid'
  const [selectedEvent, setSelectedEvent] = useState(null);

  // Helper to check if any filters are active
  const hasActiveFilters = () => {
    return selectedCamera !== 'All Cameras' || nameFilter.trim() !== '' || (fromDate !== null || toDate !== null);
  };

  // Helper to calculate date range text
  const getDateRangeText = () => {
    if (!fromDate || !toDate) return 'No dates selected';
    const days = differenceInDays(toDate, fromDate);
    return `Date range: ${days} days selected`;
  };

  const loadCameras = useCallback(async () => {
    try {
      const cameraUrl = `${BASE_URL}/api/collections/cameras`;
      const response = await axios.get(cameraUrl, {
        timeout: 5000,
        headers: { 'Content-Type': 'application/json' }
      });
      if (response.data.cameras) {
        const cameraNames = response.data.cameras.map(camera => camera.name);
        // Filter out duplicate All Cameras that might come from the API
        const uniqueNames = Array.from(new Set(cameraNames)).filter(
          name => name.toLowerCase() !== 'all cameras' && name.toLowerCase() !== 'all_cameras'
        );
        setCameras(['All Cameras', ...uniqueNames]);
      }
    } catch (err) {
      console.error("Failed to load cameras", err);
    }
  }, []);

  const fetchFaces = useCallback(async (params = {}) => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`${API_BASE_URL}/filter`, {
        params,
        timeout: 10000,
        headers: { 'Content-Type': 'application/json' }
      });
      return Array.isArray(response.data) ? response.data : [];
    } catch (err) {
      let errorMessage = 'Failed to fetch faces';
      if (err.code === 'ECONNABORTED') {
        errorMessage = 'Request timed out. Please check if the backend server is running.';
      } else if (err.response?.status === 400) {
        errorMessage = err.response.data.detail || 'Invalid request';
      } else {
        errorMessage = `Error: ${err.message}`;
      }
      setError(errorMessage);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const buildParams = useCallback((overrides = {}) => {
    const params = {
      camera: selectedCamera === 'All Cameras' ? 'all_cameras' : selectedCamera,
      ...overrides,
    };

    // Only include dates if they exist (handling null)
    const activeFrom = overrides.from_date !== undefined ? overrides.from_date : (fromDate ? format(fromDate, 'yyyy-MM-dd') : null);
    const activeTo = overrides.to_date !== undefined ? overrides.to_date : (toDate ? format(toDate, 'yyyy-MM-dd') : null);

    if (activeFrom) params.from_date = activeFrom;
    if (activeTo) params.to_date = activeTo;

    const activeName = overrides.name !== undefined ? overrides.name : nameFilter.trim();
    if (activeName) {
      params.name = activeName;
    } else if (params.name !== undefined) {
      delete params.name;
    }
    return params;
  }, [fromDate, toDate, selectedCamera, nameFilter]);

  const getTabOverrides = useCallback((tab) => {
    if (tab === 'known') return { face_type: 'known' };
    if (tab === 'unknown') return { face_type: 'unknown' };
    return {};
  }, []);

  const handleFilter = useCallback(async (overrides = {}, targetTab = null) => {
    const tabToUse = targetTab !== null ? targetTab : activeTab;

    if (fromDate && toDate && fromDate > toDate) {
      setError('From date cannot be later than To date');
      return;
    }

    const mergedOverrides = { ...getTabOverrides(tabToUse), ...overrides };
    const params = buildParams(mergedOverrides);

    const data = await fetchFaces(params);
    setFaces(data);
  }, [fromDate, toDate, fetchFaces, buildParams, getTabOverrides, activeTab]);

  const handleTabChange = useCallback((tab) => {
    setActiveTab(tab);
    handleFilter({}, tab);
  }, [handleFilter]);

  const onSearch = () => {
    handleFilter({}, activeTab);
  };

  const onClear = () => {
    setSelectedCamera('All Cameras');
    setNameFilter('');
    setFromDate(null);
    setToDate(null);
    handleFilter({
      camera: 'all_cameras',
      name: '',
      from_date: null,
      to_date: null
    }, activeTab);
  };

  const removeFilter = (type) => {
    let overrides = {};
    if (type === 'camera') {
      setSelectedCamera('All Cameras');
      overrides.camera = 'all_cameras';
    }
    if (type === 'date') {
      setFromDate(null);
      setToDate(null);
      overrides.from_date = null;
      overrides.to_date = null;
    }
    handleFilter(overrides, activeTab);
  };

  useEffect(() => {
    loadCameras();
    handleFilter({}, 'all');
  }, []);

  return (
    <div className="face-events-page">
      {/* Tabs */}
      <div className="face-events-tabs">
        <button
          className={`face-events-tab ${activeTab === 'all' ? 'active' : ''}`}
          onClick={() => handleTabChange('all')}
        >
          <span className="dot all"></span> All Faces
        </button>
        <button
          className={`face-events-tab ${activeTab === 'known' ? 'active' : ''}`}
          onClick={() => handleTabChange('known')}
        >
          Known Faces
        </button>
        <button
          className={`face-events-tab ${activeTab === 'unknown' ? 'active' : ''}`}
          onClick={() => handleTabChange('unknown')}
        >
          Unknown Faces
        </button>
      </div>

      {/* Filter Card */}
      <div className="filter-card">
        <div className="filter-row">
          <div className="filter-group">
            <label><Camera size={14} /> CAMERA</label>
            <div className="select-wrapper">
              <select
                value={selectedCamera}
                onChange={(e) => {
                  const newCamera = e.target.value;
                  setSelectedCamera(newCamera);
                  handleFilter({ camera: newCamera === 'All Cameras' ? 'all_cameras' : newCamera }, activeTab);
                }}
              >
                {cameras.map(camera => (
                  <option key={camera} value={camera}>{camera}</option>
                ))}
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          <div className="filter-group">
            <label><User size={14} /> NAME</label>
            <div className="input-wrapper">
              <Search size={14} className="input-icon" />
              <input
                type="text"
                placeholder="Filter by name..."
                value={nameFilter}
                onChange={(e) => setNameFilter(e.target.value)}
              />
            </div>
          </div>

          <div className="filter-group">
            <label><Calendar size={14} /> FROM</label>
            <div className="date-wrapper">
              <DatePicker
                selected={fromDate}
                onChange={date => {
                  setFromDate(date);
                  // Auto-trigger filter
                  handleFilter({ from_date: date ? format(date, 'yyyy-MM-dd') : null }, activeTab);
                }}
                dateFormat="dd-MM-yyyy"
                maxDate={toDate || new Date()}
                className="custom-datepicker"
                isClearable
                placeholderText="Select date"
              />
              <Calendar size={14} className="date-icon" />
            </div>
          </div>

          <div className="filter-group">
            <label><Calendar size={14} /> TO</label>
            <div className="date-wrapper">
              <DatePicker
                selected={toDate}
                onChange={date => {
                  setToDate(date);
                  // Auto-trigger filter
                  handleFilter({ to_date: date ? format(date, 'yyyy-MM-dd') : null }, activeTab);
                }}
                dateFormat="dd-MM-yyyy"
                minDate={fromDate}
                maxDate={new Date()}
                className="custom-datepicker"
                isClearable
                placeholderText="Select date"
              />
              <Calendar size={14} className="date-icon" />
            </div>
          </div>
        </div>

        <div className="filter-footer">
          <span className="date-range-info">
            <ClockIcon /> {getDateRangeText()}
          </span>
          <div className="action-buttons">
            {hasActiveFilters() && (
              <button className="btn-clear" onClick={onClear}>
                <X size={14} /> Clear
              </button>
            )}
            <button className="btn-search" onClick={onSearch}>
              <Search size={14} /> Search Events
            </button>
          </div>
        </div>
      </div>

      {/* Active Filters */}
      {(selectedCamera !== 'All Cameras' || (fromDate || toDate)) && (
        <div className="active-filters-bar">
          {selectedCamera !== 'All Cameras' && (
            <div className="filter-chip">
              <span className="chip-label">Camera:</span>
              <span className="chip-value">{selectedCamera}</span>
              <button onClick={() => removeFilter('camera')}><X size={12} /></button>
            </div>
          )}
          {(fromDate || toDate) && (
            <div className="filter-chip">
              <span className="chip-label">Date:</span>
              <span className="chip-value">
                {fromDate ? format(fromDate, 'yyyy-MM-dd') : 'Any'} &rarr; {toDate ? format(toDate, 'yyyy-MM-dd') : 'Any'}
              </span>
              <button onClick={() => removeFilter('date')}><X size={12} /></button>
            </div>
          )}
        </div>
      )}

      {/* Results Section */}
      <div className="results-card">
        <div className="results-header">
          <div className="header-left">
            <div className="icon-box"><List size={18} /></div>
            <div className="title-group">
              <h3>Event Results</h3>
              <span className="count">{faces.length} records found</span>
            </div>
          </div>
          <div className="view-actions">
            <div className="view-toggle">
              <button
                className={`toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
                onClick={() => setViewMode('list')}
              >
                <List size={18} />
              </button>
              <button
                className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
                onClick={() => setViewMode('grid')}
              >
                <Grid size={18} />
              </button>
            </div>
          </div>
        </div>

        {error && <div className="error-message">{error}</div>}

        <div className="results-content">
          {loading ? (
            <div className="loading-state">
              <div className="spinner"></div>
              <p>Loading events...</p>
            </div>
          ) : faces.length === 0 ? (
            <div className="empty-state">
              <Search size={48} />
              <p>No records found</p>
            </div>
          ) : viewMode === 'list' ? (
            <div className="table-responsive">
              <table className="events-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>NAME</th>
                    <th>CAMERA</th>
                    <th>DATE & TIME</th>
                    <th>TYPE</th>
                    <th>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {faces.map((face, index) => (
                    <tr key={`${face.image_path}-${index}`}>
                      <td>{index + 1}</td>
                      <td>
                        <div className="user-cell">
                          <div className="avatar-small">
                            <img
                              src={fixImageUrl(face.image_path)}
                              alt={face.name}
                              onError={(e) => { e.target.style.display = 'none' }}
                            />
                          </div>
                          <span>{face.name}</span>
                        </div>
                      </td>
                      <td>{face.camera}</td>
                      <td>{format(new Date(face.timestamp), 'yyyy-MM-dd HH:mm:ss')}</td>
                      <td>
                        <span className={`badge ${face.name === 'Unknown' ? 'badge-unknown' : 'badge-known'}`}>
                          {face.name === 'Unknown' ? 'Unknown' : 'Known'}
                        </span>
                      </td>
                      <td>
                        <button className="btn-action" onClick={() => setSelectedEvent(face)}>View</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="faces-grid">
              {faces.map((face, index) => (
                <div
                  key={`${face.image_path}-${index}`}
                  onClick={() => setSelectedEvent(face)}
                  style={{ cursor: 'pointer' }}
                >
                  <FaceCard
                    imagePath={face.image_path}
                    name={face.name}
                    camera={face.camera}
                    timestamp={face.timestamp}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* View Face Modal */}
      {selectedEvent && createPortal(
        <div className="face-event-modal-overlay" onClick={() => setSelectedEvent(null)}>
          <div className="face-event-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Event Details</h3>
              <button className="close-btn" onClick={() => setSelectedEvent(null)}><X size={20} /></button>
            </div>
            <div className="modal-body">
              <div className="modal-image-container">
                <img
                  src={fixImageUrl(selectedEvent.image_path)}
                  alt={selectedEvent.name}
                  onError={(e) => { e.target.src = '/placeholder-face.jpg'; e.target.style.opacity = 0.5; }}
                  className="modal-face-image"
                />
              </div>
              <div className="modal-details">
                <p><strong>Name:</strong> <span>{selectedEvent.name}</span></p>
                <p><strong>Camera:</strong> <span>{selectedEvent.camera}</span></p>
                <p><strong>Time:</strong> <span>{format(new Date(selectedEvent.timestamp), 'yyyy-MM-dd HH:mm:ss')}</span></p>
                <p><strong>Type:</strong> <span className={`badge ${selectedEvent.name === 'Unknown' ? 'badge-unknown' : 'badge-known'}`}>{selectedEvent.name === 'Unknown' ? 'Unknown' : 'Known'}</span></p>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

const ClockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"></circle>
    <polyline points="12 6 12 12 16 14"></polyline>
  </svg>
);

export default FaceEvents;
