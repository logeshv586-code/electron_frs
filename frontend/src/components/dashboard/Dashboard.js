import React, { useState, useEffect } from 'react';
import axios from 'axios';
import useAuthStore from '../../store/authStore';
import { getApiUrl } from '../../utils/apiConfig';
import AttendanceStats from './AttendanceStats';
import AttendanceCharts from './AttendanceCharts';
import FaceRecognitionAnalytics from './FaceRecognitionAnalytics';
import './Dashboard.css';

const Dashboard = ({ setActiveTab }) => {
  const { user: currentUser, token } = useAuthStore();
  const [attendanceData, setAttendanceData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const config = {
        headers: { 'Authorization': `Bearer ${token}` }
      };

      const response = await axios.get(getApiUrl('/api/events/dashboard'), config);
      if (response.data && response.data.attendance) {
        setAttendanceData(response.data.attendance);
      }
    } catch (err) {
      setError('Failed to load dashboard data');
      console.error('Dashboard error:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="dashboard-container">
        <div className="dashboard-loading">
          <div className="loading-spinner"></div>
          <p>Loading analytics...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-container">
        <div className="dashboard-error">
          <h3>Error Loading Dashboard</h3>
          <p>{error}</p>
          <button onClick={fetchDashboardData} className="retry-button">
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Dashboard Overview</h1>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={fetchDashboardData}
            className="refresh-button"
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <span className="refresh-icon">↻</span> Refresh
          </button>
          <button
            onClick={async () => {
              try {
                const response = await axios.get(getApiUrl('/api/events/export/dashboard-pdf'), {
                  headers: { 'Authorization': `Bearer ${token}` },
                  responseType: 'blob'
                });
                const blob = new Blob([response.data], { type: 'application/pdf' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `dashboard_summary_${new Date().toISOString().split('T')[0]}.pdf`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
              } catch (err) {
                console.error('Export error:', err);
                alert('Failed to export PDF');
              }
            }}
            className="refresh-button"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'var(--primary-color)',
              color: 'white',
              border: 'none'
            }}
          >
            <span role="img" aria-label="pdf">📄</span> Export PDF
          </button>
        </div>
      </div>

      <AttendanceStats setActiveTab={setActiveTab} />
      <AttendanceCharts />

      <div className="charts-section">
        <div className="charts-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 className="charts-title">Today's Attendance</h2>
          <button
            onClick={() => setActiveTab && setActiveTab('attendance-report')}
            style={{
              background: 'transparent',
              border: '1px solid var(--primary-color)',
              color: 'var(--primary-color)',
              padding: '6px 12px',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            View Full Report
          </button>
        </div>

        <div className="table-responsive" style={{ background: 'var(--bg-panel)', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'rgba(0,0,0,0.2)', borderBottom: '1px solid var(--border-color)' }}>
                <th style={{ padding: '12px 16px', color: 'var(--text-secondary)', fontWeight: '500' }}>Name</th>
                <th style={{ padding: '12px 16px', color: 'var(--text-secondary)', fontWeight: '500' }}>Department</th>
                <th style={{ padding: '12px 16px', color: 'var(--text-secondary)', fontWeight: '500' }}>Punch In</th>
                <th style={{ padding: '12px 16px', color: 'var(--text-secondary)', fontWeight: '500' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {attendanceData.slice(0, 10).map((record, index) => (
                <tr key={index} style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <td style={{ padding: '12px 16px', color: 'var(--text-primary)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {record.photo_path ? (
                        <img src={getApiUrl(record.photo_path)} alt={record.name} style={{ width: '32px', height: '32px', borderRadius: '50%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'var(--primary-color)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 'bold' }}>
                          {record.name.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <span>{record.name}</span>
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>{record.department || '-'}</td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>{record.punch_in || '-'}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{
                      padding: '4px 8px',
                      borderRadius: '12px',
                      fontSize: '0.85rem',
                      background: record.status === 'Present' ? 'url() rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                      color: record.status === 'Present' ? '#10b981' : '#ef4444',
                      border: `1px solid ${record.status === 'Present' ? '#10b981' : '#ef4444'}`
                    }}>
                      {record.status}
                    </span>
                  </td>
                </tr>
              ))}
              {attendanceData.length === 0 && (
                <tr>
                  <td colSpan="4" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    No attendance records for today.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: '2rem' }}>
        <FaceRecognitionAnalytics />
      </div>
    </div>
  );
};

export default Dashboard;
