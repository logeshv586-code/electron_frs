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
  { value: 'BIDIRECTIONAL', label: 'Bidirectional', description: 'Uses tracked virtual-line crossing to decide IN versus OUT.' },
  { value: 'REFERENCE_ONLY', label: 'Reference only', description: 'Stores recognition evidence but never changes attendance.' },
];

const roleDirection = (role) => {
  if (role === 'ENTRY') return 'IN';
  if (role === 'EXIT') return 'OUT';
  if (role === 'REFERENCE_ONLY') return 'NONE';
  return 'AUTO';
};

const clampCoordinate = (value) => {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(1, Math.max(0, parsed));
};

const AddCameraForm = ({ collectionId, onClose, editingCamera = null }) => {
  const { addCamera, updateCamera, removeCamera, collections = [], activeCollection } = useCameras();
  const token = useAuthStore((state) => state.token);
  const currentUser = useAuthStore((state) => state.user);
  const [cameraName, setCameraName] = useState('');
  const [location, setLocation] = useState('');
  const [siteId, setSiteId] = useState('');
  const [zoneId, setZoneId] = useState('');
  const [streamUrl, setStreamUrl] = useState('');
  const [cameraRole, setCameraRole] = useState('BIDIRECTIONAL');
  const [direction, setDirection] = useState('AUTO');
  const [lineX1, setLineX1] = useState(0.5);
  const [lineY1, setLineY1] = useState(0.1);
  const [lineX2, setLineX2] = useState(0.5);
  const [lineY2, setLineY2] = useState(0.9);
  const [inSide, setInSide] = useState('POSITIVE');
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
      setLineX1(editingCamera.line_x1 ?? 0.5);
      setLineY1(editingCamera.line_y1 ?? 0.1);
      setLineX2(editingCamera.line_x2 ?? 0.5);
      setLineY2(editingCamera.line_y2 ?? 0.9);
      setInSide(editingCamera.in_side || 'POSITIVE');
      setSelectedCollection(editingCamera.collection_id || collectionId || activeCollection || 'default');
    } else {
      setCameraName('');
      setLocation('');
      setSiteId('');
      setZoneId('');
      setStreamUrl('');
      setCameraRole('BIDIRECTIONAL');
      setDirection('AUTO');
      setLineX1(0.5);
      setLineY1(0.1);
      setLineX2(0.5);
      setLineY2(0.9);
      setInSide('POSITIVE');
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

    if (cameraRole === 'BIDIRECTIONAL' && direction === 'AUTO') {
      const coordinates = [lineX1, lineY1, lineX2, lineY2].map(Number);
      if (coordinates.some((value) => !Number.isFinite(value) || value < 0 || value > 1)) {
        setError('Virtual-line coordinates must be between 0 and 1.');
        return false;
      }
      if (Number(lineX1) === Number(lineX2) && Number(lineY1) === Number(lineY2)) {
        setError('Virtual line must have two different points.');
        return false;
      }
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

    const useVirtualLine = cameraRole === 'BIDIRECTIONAL' && direction === 'AUTO';
    const attendanceFields = {
      site_id: siteId.trim() || null,
      zone_id: zoneId.trim() || null,
      camera_role: cameraRole,
      direction,
      line_x1: useVirtualLine ? clampCoordinate(lineX1) : null,
      line_y1: useVirtualLine ? clampCoordinate(lineY1) : null,
      line_x2: useVirtualLine ? clampCoordinate(lineX2) : null,
      line_y2: useVirtualLine ? clampCoordinate(lineY2) : null,
      in_side: useVirtualLine ? inSide : 'POSITIVE',
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
    if (!editingCamera || currentUser?.role !== 'SuperAdmin') return;
    try {
      await removeCamera(editingCamera.id);
      setShowDeleteConfirm(false);
      if (onClose) onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Failed to delete camera.');
    }
  };

  const roleDescription = ROLE_OPTIONS.find((item) => item.value === cameraRole)?.description;
  const showVirtualLine = cameraRole === 'BIDIRECTIONAL' && direction === 'AUTO';

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

        {showVirtualLine && (
          <div className="virtual-line-panel">
            <div className="camera-form-section-title">Virtual crossing line</div>
            <p className="field-help">Coordinates are normalized to the camera frame: 0 is top/left and 1 is bottom/right. The default creates a vertical center line.</p>
            <div className="camera-form-grid three-column">
              <label className="form-group"><span>Start X</span><input type="number" min="0" max="1" step="0.01" value={lineX1} onChange={(e) => setLineX1(e.target.value)} /></label>
              <label className="form-group"><span>Start Y</span><input type="number" min="0" max="1" step="0.01" value={lineY1} onChange={(e) => setLineY1(e.target.value)} /></label>
              <label className="form-group"><span>IN side</span><select value={inSide} onChange={(e) => setInSide(e.target.value)}><option value="POSITIVE">Positive side</option><option value="NEGATIVE">Negative side</option></select></label>
              <label className="form-group"><span>End X</span><input type="number" min="0" max="1" step="0.01" value={lineX2} onChange={(e) => setLineX2(e.target.value)} /></label>
              <label className="form-group"><span>End Y</span><input type="number" min="0" max="1" step="0.01" value={lineY2} onChange={(e) => setLineY2(e.target.value)} /></label>
            </div>
          </div>
        )}

        {isValidating && <div className="validation-status">Validating stream and tenant configuration...</div>}
        {validationResult?.valid && <div className="validation-success">Camera configuration validated.</div>}

        <div className="form-actions camera-form-actions">
          <button type="submit" className="primary-button" disabled={isValidating}>{isValidating ? 'Validating...' : (editingCamera ? 'Save changes' : 'Add camera')}</button>
          <button type="button" className="cancel-button" onClick={onClose} disabled={isValidating}>Cancel</button>
          {editingCamera && currentUser?.role === 'SuperAdmin' && <button type="button" className="delete-button" onClick={() => setShowDeleteConfirm(true)} disabled={isValidating}><Trash2 size={14} /> Delete</button>}
        </div>
      </form>

      {showDeleteConfirm && currentUser?.role === 'SuperAdmin' && (
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
