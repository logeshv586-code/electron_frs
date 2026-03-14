import React, { useState, useEffect } from 'react';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import { Users, UserPlus, Edit2, Trash2, X, Shield, Search, Check, FileText } from 'lucide-react';
import './UserManagement.css';

const UserManagement = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    role: 'Admin',
    max_users_limit: 0,
    max_cameras_limit: 0,
    assigned_menus: [],
    license_duration: '1y', // '1y' | '2y' | 'custom'
    license_start_date: '',
    license_end_date: '',
    company_name: '',
    company_id: ''
  });

  const availableMenus = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'registration', label: 'Registration' },
    { id: 'gallery', label: 'Gallery' },
    { id: 'events', label: 'Events' },
    { id: 'video', label: 'Video Processing' },
    { id: 'camera', label: 'Camera Management' },
    { id: 'stream-viewer', label: 'Stream Viewer' },
    { id: 'users', label: 'User Management' },
    { id: 'settings', label: 'Settings' },
  ];

  const { user: currentUser, token } = useAuthStore();

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/users/`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) throw new Error('Failed to fetch users');

      const data = await response.json();
      setUsers(data.users);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: name.includes('limit') ? parseInt(value) || 0 : value
    }));
  };

  const handleLicenseDurationChange = (e) => {
    const value = e.target.value;
    const now = new Date();
    let startISO = new Date(now).toISOString();
    let endISO = '';
    if (value === '1y') {
      const end = new Date(now);
      end.setFullYear(end.getFullYear() + 1);
      endISO = end.toISOString();
    } else if (value === '2y') {
      const end = new Date(now);
      end.setFullYear(end.getFullYear() + 2);
      endISO = end.toISOString();
    }
    setFormData(prev => ({
      ...prev,
      license_duration: value,
      license_start_date: value === 'custom' ? prev.license_start_date : startISO,
      license_end_date: value === 'custom' ? prev.license_end_date : endISO
    }));
  };

  const handleMenuChange = (menuId) => {
    setFormData(prev => {
      const currentMenus = prev.assigned_menus || [];
      if (currentMenus.includes(menuId)) {
        return { ...prev, assigned_menus: currentMenus.filter(id => id !== menuId) };
      } else {
        return { ...prev, assigned_menus: [...currentMenus, menuId] };
      }
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const endpoint = isEditing
        ? `${API_BASE_URL}/api/users/${formData.username}`
        : `${API_BASE_URL}/api/users/`;

      const method = isEditing ? 'PUT' : 'POST';

      const body = { ...formData };
      if (isEditing) {
        // Only send updates if editing
        delete body.username; // Can't change username
        if (!body.password) {
          delete body.password; // Don't send empty password
        }
      }
      // Normalize license fields: only include for Admin when SuperAdmin is acting
      if (!((currentUser.role === 'SuperAdmin') && (formData.role === 'Admin'))) {
        delete body.license_start_date;
        delete body.license_end_date;
        delete body.license_duration;
      }
      // If custom, ensure dates exist
      if (body.license_duration === 'custom') {
        if (!body.license_start_date || !body.license_end_date) {
          alert('Please select start and end dates for custom licence.');
          return;
        }
      }
      // Remove duration helper from payload
      delete body.license_duration;

      const response = await fetch(endpoint, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          ...body,
          company_name: formData.role === 'Admin' ? formData.company_name : undefined,
          company_id: formData.role === 'Admin' ? formData.company_id : undefined
        })
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Operation failed');
      }

      setShowModal(false);
      setFormData({
        username: '',
        password: '',
        role: 'Admin',
        email: '',
        max_users_limit: 0,
        max_cameras_limit: 0,
        assigned_menus: [],
        license_duration: '1y',
        license_start_date: '',
        license_end_date: ''
      });
      setIsEditing(false);
      fetchUsers();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDelete = async (username) => {
    if (!window.confirm(`Are you sure you want to delete ${username}?`)) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/users/${username}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) throw new Error('Failed to delete user');

      fetchUsers();
    } catch (err) {
      alert(err.message);
    }
  };

  const openEditModal = (user) => {
    setFormData({
      username: user.username,
      password: '', // Password not required for edit
      role: user.role,
      email: user.email || '',
      max_users_limit: user.max_users_limit || 0,
      max_cameras_limit: user.max_cameras_limit || 0,
      assigned_menus: user.assigned_menus || [],
      license_duration: 'custom',
      license_start_date: user.license_start_date || '',
      license_end_date: user.license_end_date || ''
    });
    setIsEditing(true);
    setShowModal(true);
  };

  const filteredUsers = users.filter(user =>
    user.username.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.role.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return <div className="loading">Loading users...</div>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div className="user-management">
      <div className="header">
        <h2><Users size={24} /> User Management</h2>
        <div className="header-actions">
          <div className="search-bar">
            <Search size={18} className="search-icon" />
            <input
              type="text"
              placeholder="Search users..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <button className="add-btn" onClick={() => {
            setIsEditing(false);
            setFormData({
              username: '',
              password: '',
              role: currentUser.role === 'SuperAdmin' ? 'Admin' : 'Supervisor',
              max_users_limit: 0,
              max_cameras_limit: 0,
              assigned_menus: ['dashboard'] // Default
            });
            setShowModal(true);
          }}>
            <UserPlus size={18} /> Add User
          </button>
          <button
            className="export-btn-pdf"
            onClick={async () => {
              try {
                const response = await fetch(`${API_BASE_URL}/api/events/export/employees-pdf`, {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                if (!response.ok) throw new Error('Failed to export PDF');
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'employee_registration_report.pdf';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
              } catch (err) {
                alert('PDF Export Error: ' + err.message);
              }
            }}
            style={{
              background: '#1e293b',
              color: 'white',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: '500'
            }}
          >
            <FileText size={18} /> PDF Report
          </button>
        </div>
      </div>

      <div className="users-table-container">
        <table className="users-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Email</th>
              <th>Created By</th>
              {currentUser.role === 'SuperAdmin' && <th>Max Users</th>}
              <th>Max Cameras</th>
              {currentUser.role === 'SuperAdmin' && <th>Licence End</th>}
              <th>Assigned Cameras</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map(user => (
              <tr key={user.username}>
                <td>{user.username}</td>
                <td>
                  <span className={`role-badge ${user.role.toLowerCase()}`}>
                    <Shield size={12} /> {user.role}
                  </span>
                </td>
                <td>{user.email || '-'}</td>
                <td>{user.created_by || '-'}</td>
                {currentUser.role === 'SuperAdmin' && <td>{user.max_users_limit || 'Unlimited'}</td>}
                <td>{user.max_cameras_limit || 'Unlimited'}</td>
                {currentUser.role === 'SuperAdmin' && (
                  <td>{user.license_end_date ? new Date(user.license_end_date).toLocaleDateString() : '-'}</td>
                )}
                <td>{user.assigned_cameras ? user.assigned_cameras.length : 0}</td>
                <td className="actions-cell">
                  <div className="actions-wrapper">
                    {user.role !== 'SuperAdmin' && (
                      <>
                        <button className="action-btn edit" onClick={() => openEditModal(user)} title="Edit">
                          <Edit2 size={16} />
                        </button>
                        <button className="action-btn delete" onClick={() => handleDelete(user.username)} title="Delete">
                          <Trash2 size={16} />
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Wide Modal Form */}
      {showModal && (
        <>
          <div className="modal-overlay" onClick={() => setShowModal(false)}>
            <div className="wide-modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>{isEditing ? 'Edit User' : 'Create New User'}</h3>
                <div className="modal-header-actions">
                  <button type="button" className="header-cancel-btn" onClick={() => setShowModal(false)}>Cancel</button>
                  <button type="submit" form="user-form" className="header-submit-btn">
                    {!isEditing && <span style={{ marginRight: '4px' }}>✦</span>}
                    {isEditing ? 'Update User' : 'Create User'}
                  </button>
                  <button type="button" className="modal-close" onClick={() => setShowModal(false)}>
                    <X size={18} />
                  </button>
                </div>
              </div>

              <form id="user-form" onSubmit={handleSubmit} className="modal-form">
                <div className="form-body">
                  <div className="form-section">
                    <h4 className="section-title">ACCOUNT INFORMATION</h4>

                    <div className="form-row">
                      <div className="form-group">
                        <label>USERNAME</label>
                        <input
                          type="text"
                          name="username"
                          value={formData.username}
                          onChange={handleInputChange}
                          required
                          placeholder="Enter username"
                          disabled={isEditing}
                          className={isEditing ? 'disabled-input' : ''}
                        />
                      </div>
                      <div className="form-group">
                        <label>{isEditing ? 'RESET PASSWORD' : 'PASSWORD'}</label>
                        <input
                          type="password"
                          name="password"
                          value={formData.password}
                          onChange={handleInputChange}
                          required={!isEditing}
                          placeholder={isEditing ? "Leave blank to keep current" : "Enter password"}
                        />
                      </div>
                    </div>

                    <div className="form-row">
                      <div className="form-group">
                        <label>ROLE</label>
                        <select name="role" value={formData.role} onChange={(e) => {
                          handleInputChange(e);
                          if (e.target.value !== 'Admin') {
                            setFormData(prev => ({ ...prev, company_name: '', company_id: '' }));
                          }
                        }} disabled={isEditing}>
                          {currentUser.role === 'SuperAdmin' && <option value="Admin">Admin</option>}
                          <option value="Supervisor">Supervisor</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <label>EMAIL (FOR NOTIFICATIONS)</label>
                        <input
                          type="email"
                          name="email"
                          value={formData.email}
                          onChange={handleInputChange}
                          placeholder="Enter email address"
                        />
                      </div>
                    </div>

                    {(currentUser.role === 'SuperAdmin' && formData.role === 'Admin' && !isEditing) && (
                      <div className="form-row">
                        <div className="form-group">
                          <label>COMPANY NAME</label>
                          <input
                            type="text"
                            name="company_name"
                            value={formData.company_name}
                            onChange={(e) => {
                              const name = e.target.value;
                              const slug = name.toLowerCase().replace(/ /g, '-').replace(/[^\w-]/g, '');
                              setFormData(prev => ({ ...prev, company_name: name, company_id: slug }));
                            }}
                            required
                            placeholder="e.g. Acme Corp"
                          />
                        </div>
                        <div className="form-group">
                          <label>COMPANY ID (SLUG)</label>
                          <input
                            type="text"
                            name="company_id"
                            value={formData.company_id}
                            onChange={handleInputChange}
                            required
                            placeholder="e.g. acme-corp"
                          />
                        </div>
                      </div>
                    )}

                    {(currentUser.role === 'SuperAdmin' && formData.role === 'Admin') && (
                      <>
                        <div className="form-row">
                          <div className="form-group">
                            <label>MAX USERS LICENSE</label>
                            <input
                              type="number"
                              name="max_users_limit"
                              value={formData.max_users_limit}
                              onChange={handleInputChange}
                              min="0"
                            />
                            <small>Set to 0 for unlimited users</small>
                          </div>
                          <div className="form-group">
                            <label>MAX CAMERAS LICENSE</label>
                            <input
                              type="number"
                              name="max_cameras_limit"
                              value={formData.max_cameras_limit}
                              onChange={handleInputChange}
                              min="0"
                            />
                            <small>Set to 0 for unlimited cameras</small>
                          </div>
                        </div>

                        <div className="form-row" style={{ gridTemplateColumns: formData.license_duration === 'custom' ? '1fr 1fr 1fr' : 'repeat(2, 1fr)' }}>
                          <div className="form-group">
                            <label>LICENCE DURATION</label>
                            <select name="license_duration" value={formData.license_duration} onChange={handleLicenseDurationChange}>
                              <option value="1y">1 Year</option>
                              <option value="2y">2 Years</option>
                              <option value="custom">Custom Range</option>
                            </select>
                          </div>
                          {formData.license_duration === 'custom' && (
                            <>
                              <div className="form-group">
                                <label>START DATE</label>
                                <input
                                  type="date"
                                  name="license_start_date"
                                  value={formData.license_start_date ? formData.license_start_date.substring(0, 10) : ''}
                                  onChange={(e) => {
                                    const d = new Date(e.target.value);
                                    setFormData(prev => ({ ...prev, license_start_date: new Date(d).toISOString() }));
                                  }}
                                />
                              </div>
                              <div className="form-group">
                                <label>END DATE</label>
                                <input
                                  type="date"
                                  name="license_end_date"
                                  value={formData.license_end_date ? formData.license_end_date.substring(0, 10) : ''}
                                  onChange={(e) => {
                                    const d = new Date(e.target.value);
                                    setFormData(prev => ({ ...prev, license_end_date: new Date(d).toISOString() }));
                                  }}
                                />
                              </div>
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </div>

                  <div className="form-section">
                    <h4 className="section-title">ASSIGNED PERMISSIONS</h4>
                    <div className="permissions-grid">
                      {availableMenus.map(menu => {
                        const isSelected = (formData.assigned_menus || []).includes(menu.id);
                        return (
                          <label key={menu.id} className={`permission-card ${isSelected ? 'selected' : ''}`}>
                            <div className="custom-checkbox">
                              {isSelected && <Check size={11} color="white" strokeWidth={3} />}
                            </div>
                            <span>{menu.label.toUpperCase()}</span>
                            <input
                              type="checkbox"
                              hidden
                              checked={isSelected}
                              onChange={() => handleMenuChange(menu.id)}
                            />
                          </label>
                        );
                      })}
                    </div>
                  </div>
                </div>

              </form>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default UserManagement;
