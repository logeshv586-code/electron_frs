import React, { useState, useRef, useEffect } from 'react';
import { User, Image as ImageIcon, Upload, Check, Info, RefreshCw, FileSpreadsheet, Folder, AlertCircle } from 'lucide-react';
import './RegistrationWidget.css';

import { API_BASE_URL as BASE_URL } from '../utils/apiConfig';

const RegistrationWidget = () => {
  const [activeMode, setActiveMode] = useState('single');
  const [formData, setFormData] = useState({
    name: '',
    age: '18',
    gender: '',
    category: ''
  });
  const [autoDetectAge, setAutoDetectAge] = useState(true);
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const [ageError, setAgeError] = useState('');
  const [categoryError, setCategoryError] = useState('');
  const fileInputRef = useRef(null);

  // Bulk registration with Excel + Folder
  const [excelFile, setExcelFile] = useState(null);
  const [selectedFolder, setSelectedFolder] = useState('');
  const [imageFilesForBulk, setImageFilesForBulk] = useState([]);
  const excelFileInputRef = useRef(null);

  // Ensure age is always 18 or above on component mount
  useEffect(() => {
    const ageNum = parseInt(formData.age, 10);
    if (!formData.age || isNaN(ageNum) || ageNum < 18) {
      setFormData(prev => ({ ...prev, age: '18' }));
      setAgeError('');
    }
  }, []);

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

    // Validate category - simplified to allow more standard input types
    if (field === 'category') {
      const categoryValue = value.trim();
      setCategoryError('');
      // Always update the form field to allow user typing freely
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
      name: '',
      age: '18',
      gender: '',
      category: ''
    });
    setImageFile(null);
    setImagePreview(null);
    setAgeError('');
    setCategoryError('');
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

    // Validate age if provided
    if (formData.age.trim()) {
      const ageNum = parseInt(formData.age.trim(), 10);
      if (isNaN(ageNum) || ageNum < 18) {
        showMessage('Age must be 18 or above', 'error');
        setAgeError('Age must be 18 or above');
        return;
      }
    }

    // Basic category check without strict pattern
    if (formData.category.trim() && formData.category.trim().length > 50) {
      showMessage('Category is too long (max 50 characters)', 'error');
      setCategoryError('Category is too long');
      return;
    }

    setIsLoading(true);
    setMessage('Registering person...');

    try {
      const formDataToSend = new FormData();
      formDataToSend.append('image', imageFile);
      formDataToSend.append('name', formData.name.trim());
      formDataToSend.append('age', autoDetectAge ? '' : (formData.age || ''));
      formDataToSend.append('gender', formData.gender);
      formDataToSend.append('category', formData.category.trim());

      const response = await fetch(`${BASE_URL}/api/registration/register/single`, {
        method: 'POST',
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

  const handleExcelFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      setExcelFile(file);
      showMessage(`Excel file selected: ${file.name}`, 'success');
    }
  };

  const handleFolderSelect = async () => {
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
      const excelBuffer = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(new Uint8Array(e.target.result));
        reader.onerror = reject;
        reader.readAsArrayBuffer(excelFile);
      });

      const result = await window.electronAPI.registerBulk(
        Array.from(excelBuffer),
        imageFilesForBulk
      );

      if (result.success) {
        const successCount = result.data.filter(r => r.status === 'success').length;
        const totalCount = result.data.length;
        showMessage(`Bulk registration completed: ${successCount}/${totalCount} successful`, 'success');

        setExcelFile(null);
        setSelectedFolder('');
        setImageFilesForBulk([]);
        if (excelFileInputRef.current) {
          excelFileInputRef.current.value = '';
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

              <div className="form-group">
                <label>Category</label>
                <input
                  type="text"
                  value={formData.category}
                  onChange={(e) => handleInputChange('category', e.target.value)}
                  placeholder="e.g., Employee, Visitor, Student"
                  disabled={isLoading}
                  className="input-clean"
                />
                {categoryError && <span className="field-error">{categoryError}</span>}
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
                <ul>
                  <li>Excel file must have a 'name' column (required)</li>
                  <li>Optional columns: 'age', 'gender', 'category'</li>
                  <li>Data folder should contain images named of each person</li>
                </ul>
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