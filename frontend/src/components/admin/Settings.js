import React, { useState, useEffect } from 'react';
import useAuthStore from '../../store/authStore';
import { Settings as SettingsIcon, Save, Mail, Server, Shield } from 'lucide-react';
import { API_BASE_URL } from '../../utils/apiConfig';
import './Settings.css';

const Settings = () => {
  const { token, user } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: '', text: '' });
  const [settings, setSettings] = useState({
    max_cameras_per_admin: 10,
    max_cameras_per_supervisor: 5,
    require_approval_for_new_users: false,
    smtp_host: '',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    smtp_use_tls: true,
    email_from: '',
    attendance: {
      punch_in: '09:30',
      punch_out: '18:00',
      working_hours: 8,
      grace_minutes: 15,
      min_hours_present: 4.0,
      overtime_after: 9.0
    }
  });

  useEffect(() => {
    if (user?.role === 'SuperAdmin') {
      fetchSettings();
    }
  }, [user]);

  const fetchSettings = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/users/settings/system`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (response.ok) {
        const data = await response.json();
        const incomingSettings = data.settings || {};
        setSettings(prev => ({
          ...prev,
          ...incomingSettings,
          attendance: {
            ...prev.attendance,
            ...(incomingSettings.attendance || {})
          }
        }));
      }
    } catch (err) {
      console.error('Failed to fetch settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;

    if (name.startsWith('attendance.')) {
      const field = name.split('.')[1];
      setSettings(prev => ({
        ...prev,
        attendance: {
          ...prev.attendance,
          [field]: type === 'number' ? parseFloat(value) || 0 : value
        }
      }));
    } else {
      setSettings(prev => ({
        ...prev,
        [name]: type === 'checkbox' ? checked : (type === 'number' ? parseInt(value) || 0 : value)
      }));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setMessage({ type: '', text: '' });
      const response = await fetch(`${API_BASE_URL}/api/users/settings/system`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(settings)
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'Settings updated successfully' });
      } else {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to update settings');
      }
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setLoading(false);
    }
  };

  if (user?.role !== 'SuperAdmin' && user?.role !== 'Admin') {
    return <div className="settings-container">Access Denied</div>;
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h2><SettingsIcon size={24} /> System Settings</h2>
        <p>Configure global system parameters and email notifications</p>
      </div>

      {message.text && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <form onSubmit={handleSubmit} className="settings-form">
        {user?.role === 'SuperAdmin' && (
          <>
            <div className="settings-section">
              <div className="section-title">
                <Shield size={18} />
                <h3>General Limits</h3>
              </div>
              <div className="settings-grid">
                <div className="form-group">
                  <label>Max Cameras per Admin</label>
                  <input
                    type="number"
                    name="max_cameras_per_admin"
                    value={settings.max_cameras_per_admin}
                    onChange={handleInputChange}
                    min="1"
                  />
                </div>
                <div className="form-group">
                  <label>Max Cameras per Supervisor</label>
                  <input
                    type="number"
                    name="max_cameras_per_supervisor"
                    value={settings.max_cameras_per_supervisor}
                    onChange={handleInputChange}
                    min="1"
                  />
                </div>
              </div>
            </div>

            <div className="settings-section">
              <div className="section-title">
                <Mail size={18} />
                <h3>Email Configuration (SMTP)</h3>
              </div>
              <p className="section-desc">Configure SMTP settings to send license expiry notifications to Admins.</p>
              <div className="settings-grid">
                <div className="form-group">
                  <label>SMTP Host</label>
                  <input
                    type="text"
                    name="smtp_host"
                    value={settings.smtp_host}
                    onChange={handleInputChange}
                    placeholder="e.g. smtp.gmail.com"
                  />
                </div>
                <div className="form-group">
                  <label>SMTP Port</label>
                  <input
                    type="number"
                    name="smtp_port"
                    value={settings.smtp_port}
                    onChange={handleInputChange}
                  />
                </div>
                <div className="form-group">
                  <label>SMTP User</label>
                  <input
                    type="text"
                    name="smtp_user"
                    value={settings.smtp_user}
                    onChange={handleInputChange}
                    placeholder="your-email@example.com"
                  />
                </div>
                <div className="form-group">
                  <label>SMTP Password</label>
                  <input
                    type="password"
                    name="smtp_password"
                    value={settings.smtp_password}
                    onChange={handleInputChange}
                    placeholder="••••••••"
                  />
                </div>
                <div className="form-group">
                  <label>Email From Address</label>
                  <input
                    type="text"
                    name="email_from"
                    value={settings.email_from}
                    onChange={handleInputChange}
                    placeholder="noreply@example.com"
                  />
                </div>
                <div className="form-group checkbox-group">
                  <label>
                    <input
                      type="checkbox"
                      name="smtp_use_tls"
                      checked={settings.smtp_use_tls}
                      onChange={handleInputChange}
                    />
                    Use TLS/SSL
                  </label>
                </div>
              </div>
            </div>

            <div className="settings-section">
              <div className="section-title">
                <Server size={18} />
                <h3>Attendance Configuration</h3>
              </div>
              <p className="section-desc">Set global thresholds for punch-in, punch-out, and daily targets.</p>
              <div className="settings-grid">
                <div className="form-group">
                  <label>Punch In Time (Late Threshold)</label>
                  <input
                    type="time"
                    name="attendance.punch_in"
                    value={settings.attendance?.punch_in || '09:30'}
                    onChange={handleInputChange}
                  />
                </div>
                <div className="form-group">
                  <label>Punch Out Time</label>
                  <input
                    type="time"
                    name="attendance.punch_out"
                    value={settings.attendance?.punch_out || '18:00'}
                    onChange={handleInputChange}
                  />
                </div>
                <div className="form-group">
                  <label>Target Working Hours</label>
                  <input
                    type="number"
                    name="attendance.working_hours"
                    value={settings.attendance?.working_hours || 8}
                    onChange={handleInputChange}
                    min="1"
                    max="24"
                  />
                </div>
                <div className="form-group">
                  <label>Grace Period (Minutes)</label>
                  <input
                    type="number"
                    name="attendance.grace_minutes"
                    value={settings.attendance?.grace_minutes || 0}
                    onChange={handleInputChange}
                    min="0"
                    max="120"
                  />
                </div>
                <div className="form-group">
                  <label>Min Hours Present (Threshold)</label>
                  <input
                    type="number"
                    name="attendance.min_hours_present"
                    value={settings.attendance?.min_hours_present || 0}
                    onChange={handleInputChange}
                    min="0"
                    max="24"
                    step="0.5"
                  />
                </div>
                <div className="form-group">
                  <label>Overtime After (Hours)</label>
                  <input
                    type="number"
                    name="attendance.overtime_after"
                    value={settings.attendance?.overtime_after || 0}
                    onChange={handleInputChange}
                    min="1"
                    max="24"
                    step="0.5"
                  />
                </div>
              </div>
            </div>
          </>
        )}

        {user?.role === 'Admin' && (
          <div className="settings-section">
            <div className="section-title">
              <Shield size={18} />
              <h3>Account Info</h3>
            </div>
            <p>Email settings can only be configured by SuperAdmin.</p>
          </div>
        )}

        <div className="settings-actions">
          <button type="submit" className="save-btn" disabled={loading}>
            <Save size={18} />
            {loading ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default Settings;
