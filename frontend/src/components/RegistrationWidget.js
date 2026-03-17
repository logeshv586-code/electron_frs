import React, { useState, useRef, useEffect } from 'react';
import { User, Image as ImageIcon, Upload, Check, Info, RefreshCw, FileSpreadsheet, Folder, AlertCircle, Download, FileText, Trash2 } from 'lucide-react';
import useAuthStore from '../store/authStore';
import './RegistrationWidget.css';

import { API_BASE_URL as BASE_URL } from '../utils/apiConfig';

const RegistrationWidget = () => {
  const { user: currentUser, token } = useAuthStore();
  const [activeMode, setActiveMode] = useState('list');
  const [employees, setEmployees] = useState([]);
  const [loadingEmployees, setLoadingEmployees] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [formData, setFormData] = useState({
    emp_id: '',
    name: '',
    email: '',
    phone: '',
    role: '',
    department: '',
    designation: '',
    status: 'Active',
    age: '18',
    gender: ''
  });
  const [autoDetectAge, setAutoDetectAge] = useState(true);
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const [ageError, setAgeError] = useState('');
  const fileInputRef = useRef(null);

  // Bulk registration with Excel + Folder
  const [excelFile, setExcelFile] = useState(null);
  const [selectedFolder, setSelectedFolder] = useState('');
  const [imageFilesForBulk, setImageFilesForBulk] = useState([]);
  const excelFileInputRef = useRef(null);
  const browserFolderInputRef = useRef(null);

  // Ensure age is always 18 or above on component mount
  useEffect(() => {
    fetchEmployees();
    const ageNum = parseInt(formData.age, 10);
    if (!formData.age || isNaN(ageNum) || ageNum < 18) {
      setFormData(prev => ({ ...prev, age: '18' }));
      setAgeError('');
    }
  }, []);

  const fetchEmployees = async () => {
    setLoadingEmployees(true);
    try {
      const response = await fetch(`${BASE_URL}/api/registration/gallery`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await response.json();
      const empList = Object.keys(data).map(key => ({
        id: key,
        ...data[key]
      }));
      setEmployees(empList);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingEmployees(false);
    }
  };

  useEffect(() => {
    if (activeMode === 'list') {
      fetchEmployees();
    }
  }, [activeMode, token]);

  const handleInputChange = (field, value) => {
    // Validate age - must be 18 or above
    if (field === 'age') {
      const ageValue = value.trim();
      if (ageValue === '') {
        // If empty, set to 18 as default
        setAgeError('');
        setFormData(prev => ({ ...prev, [field]: '18' }));
        return;
      }
      const ageNum = parseInt(ageValue, 10);
      if (isNaN(ageNum) || ageNum < 18) {
        setAgeError('Age must be 18 or above');
      } else {
        setAgeError('');
      }
    }


    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const selectImage = (event) => {
    const file = event.target.files[0];
    if (file) {
      if (!file.type.startsWith('image/')) {
        showMessage('Please select a valid image file', 'error');
        return;
      }

      setImageFile(file);

      const reader = new FileReader();
      reader.onload = (e) => {
        setImagePreview(e.target.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const showMessage = (text, type) => {
    setMessage(text);
    setMessageType(type);
    setTimeout(() => {
      setMessage('');
      setMessageType('');
    }, 5000);
  };

  const resetForm = () => {
    setFormData({
      emp_id: '',
      name: '',
      email: '',
      phone: '',
      role: '',
      department: '',
      designation: '',
      status: 'Active',
      age: '18',
      gender: ''
    });
    setImageFile(null);
    setImagePreview(null);
    setAgeError('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const registerSingle = async () => {
    // Validation
    if (!imageFile) {
      showMessage('Please select an image first', 'error');
      return;
    }

    if (!formData.name.trim()) {
      showMessage('Please enter a name', 'error');
      return;
    }

    if (!formData.emp_id.trim()) {
      showMessage('Please enter an Employee ID', 'error');
      return;
    }

    if (!formData.department.trim()) {
      showMessage('Please enter a Department', 'error');
      return;
    }

    // Validate age if provided
    if (formData.age.trim()) {
      const ageNum = parseInt(formData.age.trim(), 10);
      if (isNaN(ageNum) || ageNum < 18) {
        showMessage('Age must be 18 or above', 'error');
        setAgeError('Age must be 18 or above');
        return;
      }
    }


    setIsLoading(true);
    setMessage('Registering person...');

    try {
      const formDataToSend = new FormData();
      formDataToSend.append('image', imageFile);
      formDataToSend.append('emp_id', formData.emp_id.trim());
      formDataToSend.append('name', formData.name.trim());
      formDataToSend.append('email', formData.email.trim());
      formDataToSend.append('phone', formData.phone.trim());
      formDataToSend.append('role', formData.role.trim());
      formDataToSend.append('department', formData.department.trim());
      formDataToSend.append('designation', formData.designation.trim());
      formDataToSend.append('status', formData.status.trim());
      formDataToSend.append('age', autoDetectAge ? '' : (formData.age || ''));
      formDataToSend.append('gender', formData.gender);

      const response = await fetch(`${BASE_URL}/api/registration/register/single`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        },
        body: formDataToSend,
      });

      const result = await response.json();

      if (response.ok && result.status === 'success') {
        const extra = result.age_range
          ? ` Age range: ${result.age_range}${result.age_source ? ` (${result.age_source})` : ''}.`
          : '';
        showMessage(`Successfully registered ${formData.name}!${extra}`, 'success');
        resetForm();
      } else {
        // FastAPI returns error messages in the 'detail' field for HTTPException
        const errorMessage = result.detail || result.message || 'Registration failed';
        showMessage(errorMessage, 'error');
      }
    } catch (error) {
      console.error('Registration error:', error);
      showMessage('Failed to connect to server. Please ensure the backend is running.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleStatus = async (personId, currentStatus) => {
    const newStatus = currentStatus === 'Active' ? 'Inactive' : 'Active';
    if (!window.confirm(`Are you sure you want to mark this person as ${newStatus}?`)) {
      return;
    }

    try {
      const response = await fetch(`${BASE_URL}/api/registration/metadata/person/${personId}/status`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ status: newStatus })
      });

      if (response.ok) {
        showMessage(`Person marked as ${newStatus}`, 'success');
        fetchEmployees(); // Refresh list
      } else {
        const error = await response.json();
        showMessage(error.detail || 'Failed to update status', 'error');
      }
    } catch (err) {
      console.error('Status override error:', err);
      showMessage('Failed to connect to server', 'error');
    }
  };

  const handleDeletePerson = async (personId) => {
    if (!window.confirm(`Are you sure you want to delete this person and all their biometric data? This action cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`${BASE_URL}/api/registration/metadata/person/${personId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        showMessage('Person deleted successfully', 'success');
        fetchEmployees(); // Refresh list
      } else {
        const error = await response.json();
        showMessage(error.detail || 'Failed to delete person', 'error');
      }
    } catch (err) {
      console.error('Delete error:', err);
      showMessage('Failed to connect to server', 'error');
    }
  };

  const handleExcelFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      setExcelFile(file);
      showMessage(`Excel file selected: ${file.name}`, 'success');
    }
  };

  const handleBrowserFolderSelect = (event) => {
    const files = Array.from(event.target.files);
    
    // Filter only images
    const validExtensions = ['.jpg', '.jpeg', '.png'];
    const imageFiles = files.filter(f => {
      const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
      return validExtensions.includes(ext);
    });

    if (imageFiles.length > 0) {
      setSelectedFolder(`Browser Folder (${imageFiles.length} files)`);
      setImageFilesForBulk(imageFiles);
      showMessage(`Folder selected: ${imageFiles.length} image(s) found`, 'success');
    } else {
      showMessage('Folder selected but no image files found', 'error');
      setImageFilesForBulk([]);
      setSelectedFolder('');
    }
  };

  const handleFolderSelect = async () => {
    if (!window.electronAPI) {
      // Browser fallback
      if (browserFolderInputRef.current) {
        browserFolderInputRef.current.click();
      }
      return;
    }

    try {
      const result = await window.electronAPI.selectFolder();
      if (result.success && result.folderPath) {
        setSelectedFolder(result.folderPath);
        showMessage('Scanning folder for images...', 'success');

        const scanResult = await window.electronAPI.scanFolderForImages(result.folderPath);
        if (scanResult.success && scanResult.count > 0) {
          setImageFilesForBulk(scanResult.files);
          showMessage(`Folder selected: ${scanResult.count} image(s) found`, 'success');
        } else if (scanResult.success && scanResult.count === 0) {
          showMessage('Folder selected but no image files found', 'error');
          setImageFilesForBulk([]);
        } else {
          showMessage('Failed to scan folder', 'error');
          setImageFilesForBulk([]);
        }
      }
    } catch (error) {
      console.error('Error selecting folder:', error);
      showMessage('Failed to select folder', 'error');
      setImageFilesForBulk([]);
    }
  };

  const handleBulkRegistration = async () => {
    if (!excelFile) {
      showMessage('Please select an Excel file first', 'error');
      return;
    }

    if (imageFilesForBulk.length === 0) {
      showMessage('Please select a data folder with image files first', 'error');
      return;
    }

    setIsLoading(true);
    setMessage('Processing bulk registration...');

    try {
      let result;
      
      if (window.electronAPI) {
        const excelBuffer = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (e) => resolve(new Uint8Array(e.target.result));
          reader.onerror = reject;
          reader.readAsArrayBuffer(excelFile);
        });

        result = await window.electronAPI.registerBulk(
          Array.from(excelBuffer),
          imageFilesForBulk
        );
      } else {
        // Browser fallback using FormData
        const formDataToSend = new FormData();
        formDataToSend.append('excel_file', excelFile);
        
        imageFilesForBulk.forEach(file => {
          const path = file.webkitRelativePath || file.name;
          formDataToSend.append('image_files', file, path);
        });

        const response = await fetch(`${BASE_URL}/api/registration/register/bulk`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          body: formDataToSend,
        });
        
        const data = await response.json();
        result = {
          success: response.ok,
          data: data,
          error: data.detail || data.message
        };
      }

      if (result.success) {
        let successCount = 0;
        let totalCount = 0;
        if (Array.isArray(result.data)) {
          successCount = result.data.filter(r => r.status === 'success').length;
          totalCount = result.data.length;
        }
        
        showMessage(`Bulk registration completed: ${successCount} successful`, 'success');

        setExcelFile(null);
        setSelectedFolder('');
        setImageFilesForBulk([]);
        if (excelFileInputRef.current) {
          excelFileInputRef.current.value = '';
        }
        if (browserFolderInputRef.current) {
          browserFolderInputRef.current.value = '';
        }
      } else {
        showMessage(result.error || 'Bulk registration failed', 'error');
      }
    } catch (error) {
      console.error('Bulk registration error:', error);
      showMessage('Failed to process bulk registration. Please ensure the backend is running.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="registration-widget">
      <div className="registration-header-clean">
        <div className="header-title">
          <h2>Registration</h2>
          <p>Add new persons to the database</p>
        </div>
        <div className="mode-selector-pill">
          <button
            className={`mode-pill ${activeMode === 'list' ? 'active' : ''}`}
            onClick={() => setActiveMode('list')}
          >
            Employee List
          </button>
          <button
            className={`mode-pill ${activeMode === 'single' ? 'active' : ''}`}
            onClick={() => setActiveMode('single')}
          >
            Single Entry
          </button>
          <button
            className={`mode-pill ${activeMode === 'bulk' ? 'active' : ''}`}
            onClick={() => setActiveMode('bulk')}
          >
            Bulk Import
          </button>
        </div>
      </div>

      {activeMode === 'single' && (
        <div className="stepper-header">
          <div className="step active">
            <span className="step-num">1</span>
            <span className="step-text">Person Info</span>
          </div>
          <div className="step-line"></div>
          <div className="step active">
            <span className="step-num">2</span>
            <span className="step-text">Photo Upload</span>
          </div>
          <div className="step-line"></div>
          <div className="step">
            <span className="step-num">3</span>
            <span className="step-text">Review & Submit</span>
          </div>
        </div>
      )}

      {message && (
        <div className={`message-banner ${messageType}`}>
          {messageType === 'error' ? <AlertCircle size={18} /> : <Check size={18} />}
          <span>{message}</span>
        </div>
      )}

      {activeMode === 'list' && (
        <div className="employee-list-layout">
          <div className="list-controls" style={{ marginBottom: '16px', display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="Search employees..."
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(1); }}
              className="input-clean"
              style={{ maxWidth: '300px' }}
            />
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              {employees.filter(e => e.name.toLowerCase().includes(searchTerm.toLowerCase()) || (e.emp_id && e.emp_id.toLowerCase().includes(searchTerm.toLowerCase()))).length} employees
            </span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
              <button className="btn-submit-clean" onClick={async () => {
                try {
                  const response = await fetch(`${BASE_URL}/api/events/employees/export`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                  });
                  if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || 'Export failed');
                  }
                  const blob = await response.blob();
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'employees_export.csv';
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  console.error('Export error:', err);
                  showMessage(err.message || 'Failed to export employee data', 'error');
                }
              }} style={{ width: 'auto', background: 'var(--bg-panel)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}>
                <Download size={16} /> Export CSV
              </button>
              <button className="btn-submit-clean" onClick={async () => {
                try {
                  const response = await fetch(`${BASE_URL}/api/events/export/employees-pdf`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                  });
                  if (!response.ok) {
                    const errData = await response.json().catch(() => ({}));
                    throw new Error(errData.detail || 'Failed to generate PDF');
                  }
                  const blob = await response.blob();
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'employees_report.pdf';
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  console.error('Export error:', err);
                  showMessage(err.message || 'Failed to export PDF', 'error');
                }
              }} style={{ width: 'auto', background: 'var(--bg-panel)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}>
                <FileText size={16} /> Export PDF
              </button>
              <button className="btn-submit-clean" onClick={() => setActiveMode('single')} style={{ width: 'auto' }}>
                + Add Employee
              </button>
            </div>
          </div>

          <div className="table-container">
            {loadingEmployees ? (
              <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading employees...</div>
            ) : (() => {
              const filtered = employees.filter(e => e.name.toLowerCase().includes(searchTerm.toLowerCase()) || (e.emp_id && e.emp_id.toLowerCase().includes(searchTerm.toLowerCase())));
              const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
              const paginatedData = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

              return (
                <>
                  <table className="attendance-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Emp ID</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Name</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Department</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Designation</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Email</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Phone</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid var(--border-color)' }}>Status</th>
                        <th style={{ padding: '12px', textAlign: 'center', borderBottom: '1px solid var(--border-color)' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedData.map((emp, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                          <td style={{ padding: '12px' }}>{emp.emp_id || '-'}</td>
                          <td style={{ padding: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <img
                              src={emp.image_url ? `${BASE_URL}${emp.image_url}` : `${BASE_URL}/api/gallery/image/${currentUser?.company_id || 'default'}/${emp.name}/${emp.image_filename || 'original.jpg'}`}
                              alt={emp.name}
                              style={{ width: '30px', height: '30px', borderRadius: '50%', objectFit: 'cover' }}
                              onError={(e) => { e.target.style.display = 'none'; }}
                            />
                            {emp.name}
                          </td>
                          <td style={{ padding: '12px' }}>{emp.department || '-'}</td>
                          <td style={{ padding: '12px' }}>{emp.designation || '-'}</td>
                          <td style={{ padding: '12px' }}>{emp.email || '-'}</td>
                          <td style={{ padding: '12px' }}>{emp.phone || '-'}</td>
                          <td style={{ padding: '12px' }}>
                            <span style={{
                              padding: '4px 8px',
                              borderRadius: '12px',
                              fontSize: '0.8rem',
                              backgroundColor: emp.status === 'Active' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                              color: emp.status === 'Active' ? '#10b981' : '#ef4444'
                            }}>
                              {emp.status || 'Active'}
                            </span>
                          </td>
                          <td style={{ padding: '12px', textAlign: 'center' }}>
                            <button 
                              onClick={() => handleDeletePerson(emp.id)}
                              className="btn-icon-delete"
                              title="Delete Person"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: '#ef4444',
                                cursor: 'pointer',
                                padding: '4px',
                                borderRadius: '4px',
                                transition: 'background 0.2s'
                              }}
                              onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.1)'}
                              onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                            >
                              <Trash2 size={16} />
                            </button>
                          </td>
                        </tr>
                      ))}
                      {filtered.length === 0 && (
                        <tr>
                          <td colSpan="8" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>No employees found</td>
                        </tr>
                      )}
                    </tbody>
                  </table>

                  {/* Pagination */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 0', flexWrap: 'wrap', gap: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Rows per page:</span>
                      <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setCurrentPage(1); }} className="select-clean" style={{ width: 'auto', padding: '4px 8px' }}>
                        <option value={10}>10</option>
                        <option value={25}>25</option>
                        <option value={50}>50</option>
                      </select>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Page {currentPage} of {totalPages}</span>
                      <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1} style={{ padding: '4px 10px', cursor: 'pointer', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'var(--bg-panel)', color: 'var(--text-primary)' }}>←</button>
                      <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages} style={{ padding: '4px 10px', cursor: 'pointer', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'var(--bg-panel)', color: 'var(--text-primary)' }}>→</button>
                    </div>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}

      {activeMode === 'single' && (
        <div className="single-registration-layout">
          {/* Left Panel: Person Info */}
          <div className="reg-card person-info-card">
            <div className="card-header">
              <div className="icon-box blue">
                <User size={20} />
              </div>
              <div className="header-text">
                <h3>Person Information</h3>
                <p>Fill in the individual's basic identity details</p>
              </div>
            </div>

            <div className="card-content">
              <div className="form-group">
                <label>Full Name <span className="required">*</span></label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  placeholder="Enter person's full name"
                  disabled={isLoading}
                  className="input-clean"
                />
              </div>

              <div className="form-row-split">
                <div className="form-group">
                  <label>Emp ID <span className="required">*</span></label>
                  <input
                    type="text"
                    value={formData.emp_id}
                    onChange={(e) => handleInputChange('emp_id', e.target.value)}
                    placeholder="e.g. EMP1001"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
                <div className="form-group">
                  <label>Department <span className="required">*</span></label>
                  <input
                    type="text"
                    value={formData.department}
                    onChange={(e) => handleInputChange('department', e.target.value)}
                    placeholder="e.g. IT"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
              </div>

              <div className="form-row-split">
                <div className="form-group">
                  <label>Designation</label>
                  <input
                    type="text"
                    value={formData.designation}
                    onChange={(e) => handleInputChange('designation', e.target.value)}
                    placeholder="e.g. Developer"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => handleInputChange('email', e.target.value)}
                    placeholder="e.g. john@company.com"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
              </div>

              <div className="form-row-split">
                <div className="form-group">
                  <label>Phone</label>
                  <input
                    type="text"
                    value={formData.phone}
                    onChange={(e) => handleInputChange('phone', e.target.value)}
                    placeholder="e.g. 1234567890"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
                <div className="form-group">
                  <label>Role</label>
                  <input
                    type="text"
                    value={formData.role}
                    onChange={(e) => handleInputChange('role', e.target.value)}
                    placeholder="e.g. Staff"
                    disabled={isLoading}
                    className="input-clean"
                  />
                </div>
              </div>

              <div className="form-row-split">
                <div className="form-group">
                  <label>Status</label>
                  <select
                    value={formData.status}
                    onChange={(e) => handleInputChange('status', e.target.value)}
                    disabled={isLoading}
                    className="select-clean"
                  >
                    <option value="Active">Active</option>
                    <option value="Inactive">Inactive</option>
                  </select>
                </div>
              </div>

              <div className="form-row-split">
                <div className="form-group age-group">
                  <label>
                    Age
                    <span className="ai-badge-clean">AI</span>
                  </label>

                  {autoDetectAge ? (
                    <div
                      className="auto-detect-box selected"
                      onClick={() => setAutoDetectAge(false)}
                      title="Click to switch to manual age entry"
                    >
                      <div className="check-circle">
                        <Check size={14} />
                      </div>
                      <div className="auto-detect-text">
                        <strong>Auto-detect from photo</strong>
                        <span>Uses AI to estimate age range from the uploaded photo</span>
                      </div>
                    </div>
                  ) : (
                    <div className="manual-age-container-clean">
                      <div className="age-stepper-clean">
                        <button
                          type="button"
                          className="step-btn-clean"
                          onClick={() => {
                            const current = parseInt(formData.age || '18', 10);
                            const next = isNaN(current) ? 18 : Math.max(18, current - 1);
                            setAgeError('');
                            setFormData(prev => ({ ...prev, age: String(next) }));
                          }}
                          disabled={isLoading || (() => {
                            const v = parseInt(formData.age || '18', 10);
                            return !isFinite(v) || v <= 18;
                          })()}
                        >
                          −
                        </button>
                        <input
                          type="number"
                          value={(() => {
                            const ageValue = formData.age || '18';
                            const ageNum = parseInt(ageValue, 10);
                            const finalValue = (isNaN(ageNum) || ageNum < 18) ? '18' : String(Math.min(120, ageNum));
                            return finalValue;
                          })()}
                          readOnly
                          min={18}
                          max={120}
                          step={1}
                          disabled={isLoading}
                        />
                        <button
                          type="button"
                          className="step-btn-clean"
                          onClick={() => {
                            const current = parseInt(formData.age || '18', 10);
                            const next = isNaN(current) ? 18 : Math.min(120, current + 1);
                            setAgeError('');
                            setFormData(prev => ({ ...prev, age: String(next) }));
                          }}
                          disabled={isLoading || (() => {
                            const v = parseInt(formData.age || '18', 10);
                            return !isFinite(v) || v >= 120;
                          })()}
                        >
                          +
                        </button>
                      </div>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setAutoDetectAge(true)}
                      >
                        Use Auto-detect
                      </button>
                    </div>
                  )}

                  {ageError && <span className="field-error">{ageError}</span>}
                </div>

                <div className="form-group gender-group">
                  <label>Gender</label>
                  <select
                    value={formData.gender}
                    onChange={(e) => handleInputChange('gender', e.target.value)}
                    disabled={isLoading}
                    className="select-clean"
                  >
                    <option value="" disabled>Select Gender</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
              </div>


              <div className="info-alert">
                <Info size={16} />
                <span>Ensure the person's details match official identification documents for accuracy.</span>
              </div>
            </div>

            <div className="card-footer">
              <button
                type="button"
                className="btn-reset-clean"
                onClick={resetForm}
                disabled={isLoading}
              >
                <RefreshCw size={14} />
                Reset
              </button>
            </div>
          </div>

          {/* Right Panel: Upload Photo */}
          <div className="reg-card photo-card">
            <div className="card-header">
              <div className="icon-box blue">
                <ImageIcon size={20} />
              </div>
              <div className="header-text">
                <h3>Upload Photo</h3>
                <p>Clear front-facing portrait recommended</p>
              </div>
            </div>

            <div className="card-content fill-height">
              <div
                className={`upload-area-clean ${imagePreview ? 'has-image' : ''}`}
                onClick={() => {
                  if (!isLoading) fileInputRef.current?.click();
                }}
              >
                {imagePreview ? (
                  <div className="image-preview-clean">
                    <img src={imagePreview} alt="Preview" />
                    <button
                      type="button"
                      className="remove-image-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setImageFile(null);
                        setImagePreview(null);
                        if (fileInputRef.current) fileInputRef.current.value = '';
                      }}
                      disabled={isLoading}
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <div className="upload-placeholder-clean">
                    <div className="upload-icon-circle">
                      <ImageIcon size={32} />
                    </div>
                    <h4>Click to select an image</h4>
                    <p>or drag & drop here</p>
                    <div className="file-types">
                      <span>JPG</span>
                      <span>PNG</span>
                      <span>JPEG</span>
                    </div>
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={selectImage}
                  style={{ display: 'none' }}
                  disabled={isLoading}
                />
              </div>
            </div>

            <div className="card-footer">
              <button
                type="button"
                className="btn-submit-clean"
                onClick={registerSingle}
                disabled={isLoading || !imageFile || !formData.name.trim()}
              >
                <Check size={18} />
                {isLoading ? 'Registering...' : 'Register Person'}
              </button>
            </div>
          </div>
        </div>
      )}

      {activeMode === 'bulk' && (
        <div className="bulk-registration-layout">
          <div className="reg-card full-width">
            <div className="card-header">
              <div className="icon-box blue">
                <Folder size={20} />
              </div>
              <div className="header-text">
                <h3>Bulk Registration</h3>
                <p>Register multiple people using an Excel file and image folder</p>
              </div>
            </div>

            <div className="card-content">
              <div className="bulk-grid">
                <div className="bulk-step">
                  <h4>1. Select Excel File</h4>
                  <div
                    className={`file-select-box ${excelFile ? 'selected' : ''}`}
                    onClick={() => {
                      if (!isLoading) excelFileInputRef.current?.click();
                    }}
                  >
                    <input
                      ref={excelFileInputRef}
                      type="file"
                      accept=".xlsx,.xls"
                      onChange={handleExcelFileSelect}
                      style={{ display: 'none' }}
                      disabled={isLoading}
                    />
                    <div className="box-icon">
                      <FileSpreadsheet size={32} />
                    </div>
                    <div className="box-info">
                      <p className="box-title">{excelFile ? excelFile.name : 'Click to select Excel file'}</p>
                      <small>Supported: .xlsx, .xls</small>
                    </div>
                  </div>
                </div>

                <div className="bulk-step">
                  <h4>2. Select Data Folder</h4>
                  <input
                    ref={browserFolderInputRef}
                    type="file"
                    webkitdirectory="true"
                    directory="true"
                    onChange={handleBrowserFolderSelect}
                    style={{ display: 'none' }}
                    disabled={isLoading}
                    multiple
                  />
                  <div
                    className={`file-select-box ${selectedFolder ? 'selected' : ''}`}
                    onClick={handleFolderSelect}
                  >
                    <div className="box-icon">
                      <Folder size={32} />
                    </div>
                    <div className="box-info">
                      <p className="box-title">{selectedFolder || 'Click to select data folder'}</p>
                      <small>Folder containing person images</small>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bulk-instructions">
                <h4>Instructions</h4>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                  Please ensure your Excel file contains the following mandatory columns:
                </p>
                <ul style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '12px', paddingLeft: '20px' }}>
                  <li><strong>name</strong> (Matches the image filename)</li>
                  <li><strong>Employee Full Name</strong></li>
                  <li><strong>Employee Details</strong></li>
                  <li><strong>Designation</strong></li>
                  <li><strong>Email</strong></li>
                  <li><strong>Phone Number</strong></li>
                  <li><strong>Roles</strong></li>
                  <li><strong>Status</strong></li>
                  <li><strong>Gender</strong></li>
                </ul>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  <strong>Note:</strong> The selected Data Folder should contain images named identically to the 'name' column for each person. Optional columns: 'age', 'category'.
                </p>
              </div>
            </div>

            <div className="card-footer right-align">
              <button
                className="btn-submit-clean"
                onClick={handleBulkRegistration}
                disabled={isLoading || !excelFile || !selectedFolder}
              >
                {isLoading ? 'Processing...' : 'Start Bulk Registration'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default RegistrationWidget;