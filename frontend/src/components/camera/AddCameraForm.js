import React, { useEffect, useState } from 'react';
import { Camera, Info, MapPin, ShieldCheck, Trash2 } from 'lucide-react';
import { useCameras } from './CameraManager';
import useAuthStore from '../../store/authStore';
import { extractIPFromStreamURL, validatePrivateIP } from '../../utils/ipValidation';
import { API_BASE_URL } from '../../utils/apiConfig';
import './AddCameraForm.css';

const ROLE_OPTIONS = [
  { value: 'ENTRY', label: 'Entry', description: 'Can set the first attendance IN event.' },
  { value: 'EXIT', label: 'Exit', description: 'Can update the final attendance OUT event.' },
  { value: 'BIDIRECTIONAL', label: 'Bidirectional', description: 'Uses first valid sighting as IN and later valid sightings as OUT.' },
  { value: 'REFERENCE_ONLY', label: 'Reference only', description: 'Stores recognition evidence but never changes attendance.' },
];

const roleDirection = (role) => {
  if (role === 'ENTRY') return 'IN';
  if (role === 'EXIT') return 'OUT';
  if (role === 'REFERENCE_ONLY') return 'NONE';
  return 'AUTO';
};

const AddCameraForm = ({ collectionId, onClose, editingCamera = null }) => {
  const { addCamera, updateCamera, removeCamera, collections = [], activeCollection } = useCameras();
  const token = useAuthStore((state) => state.token);
  const [cameraName, setCameraName] = useState('');
  const [location, setLocation] = useState('');
  const [siteId, setSiteId] = useState('');
  const [zoneId, setZoneId] = useState('');
  const [streamUrl, setStreamUrl] = useState('');
  const [cameraRole, setCameraRole] = useState('BIDIRECTIONAL');
  const [direction, setDirection] = useState('AUTO');
  const [selectedCollection, setSelectedCollection] = useState(collectionId || activeCollection || 'default');
  const [error, setError] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);

  useEffect(() => {
    if (editingCamera) {
      setCameraName(editingCamera.name || '');
      setLocation(editingCamera.location || '');
      setSiteId(editingCamera.site_id || '');
      setZoneId(editingCamera.zone_id || '');
      setStreamUrl(editingCamera.streamUrl || editingCamera.rtsp_url || '');
      setCameraRole(editingCamera.camera_role || 'BIDIRECTIONAL');
      setDirection(editingCamera.direction || roleDirection(editingCamera.camera_role || 'BIDIRECTIONAL'));
      setSelectedCollection(editingCamera.collection_id || collectionId || activeCollection || 'default');
    } else {
      setCameraName('');
      setLocation('');
      setSiteId('');
      setZoneId('');
      setStreamUrl('');
      setCameraRole('BIDIRECTIONAL');
      setDirection('AUTO');
      setSelectedCollection(collectionId || activeCollection || 'default');
    }
    setError('');
    setValidationResult(null);
  }, [editingCamera, collectionId, activeCollection]);

  const handleRoleChange = (value) => {
    setCameraRole(value);
    setDirection(roleDirection(value));
  };

  const validateCameraData = async (ip, url, collectionName, excludeIp) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/validate-camera`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ip, streamUrl: url, collection_name: collectionName, exclude_ip: excludeIp }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) return { valid: false, error: result.detail || 'Camera validation failed.' };
      return result;
    } catch (requestError) {
      return { valid: false, error: 'Could not validate the camera. Check the backend connection.', type: 'network_error' };
    }
  };

  const validateForm = async () => {
    if (!cameraName.trim()) {
      setError('Camera name is required.');
      return false;
    }
    if (!streamUrl.trim()) {
      setError('Stream URL or local camera index is required.');
      return false;
    }

    const trimmedUrl = streamUrl.trim();
    const isCameraIndex = /^\d+$/.test(trimmedUrl);
    if (!isCameraIndex && !trimmedUrl.toLowerCase().startsWith('rtsp://') && !trimmedUrl.toLowerCase().startsWith('http://') && !trimmedUrl.toLowerCase().startsWith('https://')) {
      setError('Use an RTSP/HTTP/HTTPS stream URL or a local camera index such as 0.');
      return false;
    }

    let extractedIP = trimmedUrl;
    if (!isCameraIndex) {
      extractedIP = extractIPFromStreamURL(trimmedUrl);
      if (!extractedIP) {
        setError('The stream URL must contain a valid camera IP address.');
        return false;
      }
      const ipValidation = validatePrivateIP(extractedIP);
      if (!ipValidation.isValid) {
        setError('Camera IP must be inside an approved private network range.');
        return false;
      }
    }

    setIsValidating(true);
    const targetCollection = collections.find((item) => item.id === selectedCollection);
    const oldUrl = editingCamera?.streamUrl || editingCamera?.rtsp_url || '';
    const excludeIp = editingCamera ? (extractIPFromStreamURL(oldUrl) || oldUrl) : null;
    const validation = await validateCameraData(extractedIP, trimmedUrl, targetCollection?.name, excludeIp);
    setIsValidating(false);
    setValidationResult(validation);
    if (!validation.valid) {
      setError(validation.type === 'duplicate' && validation.existingCollection
        ? `${validation.error} Existing collection: ${validation.existingCollection}.`
        : (validation.error || 'Camera validation failed.'));
      return false;
    }
    return true;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setValidationResult(null);
    if (!(await validateForm())) return;

    const attendanceFields = {
      site_id: siteId.trim() || null,
      zone_id: zoneId.trim() || null,
      camera_role: cameraRole,
      direction,
    };

    try {
      if (editingCamera) {
        await updateCamera(editingCamera.id, {
          name: cameraName.trim(),
          location: location.trim(),
          streamUrl: streamUrl.trim(),
          collectionId: selectedCollection,
          ...attendanceFields,
        });
      } else {
        const created = await addCamera(cameraName.trim(), streamUrl.trim(), selectedCollection, location.trim());
        if (created?.camera?.id) {
          await updateCamera(created.camera.id, attendanceFields);
        }
      }
      if (onClose) onClose();
    } catch (submitError) {
      setError(submitError.message || `Failed to ${editingCamera ? 'update' : 'add'} camera.`);
    }
  };

  const handleDelete = async () => {
    if (!editingCamera) return;
    try {
      await removeCamera(editingCamera.id);
      setShowDeleteConfirm(false);
      if (onClose) onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Failed to delete camera.');
    }
  };

  const roleDescription = ROLE_OPTIONS.find((item) => item.value === cameraRole)?.description;

  return (
    <div className="add-camera-form product-camera-form">
      <div className="form-header">
        <div className="camera-form-title"><span><Camera size={18} /></span><div><h3>{editingCamera ? 'Edit camera' : 'Add camera'}</h3><p>Configure the stream and how this camera participates in attendance.</p></div></div>
      </div>

      <form onSubmit={handleSubmit}>
        {error && <div className="error-message camera-form-error">{error}</div>}

        <div className="camera-form-grid two-column">
          <label className="form-group"><span>Camera name</span><input value={cameraName} onChange={(event) => setCameraName(event.target.value)} placeholder="Main Gate Camera 01" required /></label>
          <label className="form-group"><span>Collection</span><select value={selectedCollection || 'default'} onChange={(event) => setSelectedCollection(event.target.value)}>{collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}{collections.length === 0 && <option value="default">Default Collection</option>}</select></label>
        </div>

        <label className="form-group"><span>Stream URL / camera index</span><input value={streamUrl} onChange={(event) => setStreamUrl(event.target.value)} placeholder="rtsp://user:password@192.168.1.100:554/stream or 0" required /></label>

        <div className="camera-form-section-title"><MapPin size={14} /> Location identity</div>
        <div className="camera-form-grid three-column">
          <label className="form-group"><span>Display location</span><input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Main Entrance" /></label>
          <label className="form-group"><span>Site ID</span><input value={siteId} onChange={(event) => setSiteId(event.target.value)} placeholder="chennai-office" /></label>
          <label className="form-group"><span>Zone ID</span><input value={zoneId} onChange={(event) => setZoneId(event.target.value)} placeholder="ground-floor-gate" /></label>
        </div>

        <div className="camera-form-section-title"><ShieldCheck size={14} /> Attendance behavior</div>
        <div className="camera-role-grid">
          {ROLE_OPTIONS.map((option) => (
            <button type="button" key={option.value} className={`camera-role-option ${cameraRole === option.value ? 'active' : ''}`} onClick={() => handleRoleChange(option.value)}>
              <span className="camera-role-radio" />
              <span><strong>{option.label}</strong><small>{option.description}</small></span>
            </button>
          ))}
        </div>

        <div className="direction-summary">
          <Info size={14} />
          <span><strong>Direction: {direction}</strong> — {roleDescription}</span>
        </div>

        {isValidating && <div className="validation-status">Validating stream and tenant configuration...</div>}
        {validationResult?.valid && <div className="validation-success">Camera configuration validated.</div>}

        <div className="form-actions camera-form-actions">
          <button type="submit" className="primary-button" disabled={isValidating}>{isValidating ? 'Validating...' : (editingCamera ? 'Save changes' : 'Add camera')}</button>
          <button type="button" className="cancel-button" onClick={onClose} disabled={isValidating}>Cancel</button>
          {editingCamera && <button type="button" className="delete-button" onClick={() => setShowDeleteConfirm(true)} disabled={isValidating}><Trash2 size={14} /> Delete</button>}
        </div>
      </form>

      {showDeleteConfirm && (
        <div className="modal-overlay">
          <div className="modal-content delete-camera-modal">
            <h3>Delete camera?</h3>
            <p>This removes the camera configuration. Historical recognition and attendance records remain in the database.</p>
            <div className="modal-actions"><button className="confirm-button danger" onClick={handleDelete}>Delete camera</button><button className="cancel-button" onClick={() => setShowDeleteConfirm(false)}>Keep camera</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AddCameraForm;
