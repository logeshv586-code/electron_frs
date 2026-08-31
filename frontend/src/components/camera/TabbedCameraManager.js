import React, { useState, useEffect } from 'react';
import { useCameras } from './CameraManager';
import { Camera, Plus, List } from 'lucide-react';
import AddCameraForm from './AddCameraForm';
import useAuthStore from '../../store/authStore';
import './TabbedCameraManager.css';

const TabbedCameraManager = ({ onClose }) => {
  const {
    collections,
    cameras,
    createCollection,
    updateCollection,
    deleteCollection,
    getCamerasByCollection,
    activateCamera,
    deactivateCamera,
    initialize,
    error
  } = useCameras();

  const currentUser = useAuthStore((state) => state.user);
  const canManageCameraConfig = ['SuperAdmin', 'Admin'].includes(currentUser?.role);
  const canDeleteCameraConfig = currentUser?.role === 'SuperAdmin';

  const [activeTab, setActiveTab] = useState('cameras');
  const [selectedCollection, setSelectedCollection] = useState('default');

  useEffect(() => {
    if (collections && collections.length > 0) {
      const collectionExists = collections.some(c => c.id === selectedCollection);
      if (!collectionExists && selectedCollection !== 'all') {
        const defaultCollection = collections.find(c => c.id === 'default');
        setSelectedCollection(defaultCollection ? 'default' : 'all');
      }
    }
  }, [collections, selectedCollection]);

  const [showAddCameraForm, setShowAddCameraForm] = useState(false);
  const [editingCamera, setEditingCamera] = useState(null);
  const [showCreateCollection, setShowCreateCollection] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState('');
  const [showEditCollection, setShowEditCollection] = useState(false);
  const [editingCollection, setEditingCollection] = useState(null);
  const [editCollectionName, setEditCollectionName] = useState('');
  const [editCollectionDescription, setEditCollectionDescription] = useState('');

  useEffect(() => {
    initialize();
  }, [initialize]);

  const tabs = [
    { id: 'cameras', label: 'Camera List', icon: List },
    ...(canManageCameraConfig ? [{ id: 'add', label: 'Add Camera', icon: Plus }] : []),
  ];

  const handleTabChange = (tabId) => {
    if (tabId === 'add' && !canManageCameraConfig) return;
    setActiveTab(tabId);
    if (tabId === 'add') {
      setShowAddCameraForm(true);
      setEditingCamera(null);
    } else {
      setShowAddCameraForm(false);
    }
  };

  const handleAddCamera = () => {
    if (!canManageCameraConfig) return;
    setActiveTab('add');
    setShowAddCameraForm(true);
    setEditingCamera(null);
  };

  const handleEditCamera = (camera) => {
    if (!canManageCameraConfig) return;
    setActiveTab('add');
    const mappedCamera = {
      ...camera,
      streamUrl: camera.streamUrl || camera.rtsp_url || camera.stream_url || ''
    };
    setEditingCamera(mappedCamera);
    setShowAddCameraForm(true);
  };

  const handleCloseCameraForm = () => {
    setShowAddCameraForm(false);
    setEditingCamera(null);
    setActiveTab('cameras');
  };

  const handleCreateCollection = async (e) => {
    e.preventDefault();
    if (!canManageCameraConfig) return;
    if (newCollectionName.trim()) {
      try {
        await createCollection(newCollectionName.trim());
        setNewCollectionName('');
        setShowCreateCollection(false);
      } catch (creationError) {
        console.error('Error creating collection:', creationError);
        alert(`Failed to create collection: ${creationError.message || 'Unknown error'}`);
      }
    }
  };

  const handleEditCollection = (collection) => {
    if (!canManageCameraConfig) return;
    setEditingCollection(collection);
    setEditCollectionName(collection.name);
    setEditCollectionDescription(collection.description || '');
    setShowEditCollection(true);
  };

  const handleUpdateCollection = async (e) => {
    e.preventDefault();
    if (!canManageCameraConfig) return;
    if (editCollectionName.trim()) {
      try {
        await updateCollection(editingCollection.id, {
          name: editCollectionName.trim(),
          description: editCollectionDescription.trim() || null
        });
        await initialize();
        setShowEditCollection(false);
        setEditingCollection(null);
        setEditCollectionName('');
        setEditCollectionDescription('');
      } catch (updateError) {
        console.error('Error updating collection:', updateError);
        alert(`Failed to update collection: ${updateError.message || 'Unknown error'}`);
      }
    }
  };

  const handleDeleteCollection = async () => {
    if (!canDeleteCameraConfig || !editingCollection) return;
    if (editingCollection.id === 'default') {
      alert('Cannot delete the default collection');
      return;
    }

    const confirmMessage = editingCollection.camera_count > 0
      ? `This collection has ${editingCollection.camera_count} camera(s). Cameras will become unassigned. Delete "${editingCollection.name}"?`
      : `Delete "${editingCollection.name}"?`;

    if (window.confirm(confirmMessage)) {
      try {
        await deleteCollection(editingCollection.id);
        setShowEditCollection(false);
        setEditingCollection(null);
        setEditCollectionName('');
        setEditCollectionDescription('');
        if (selectedCollection === editingCollection.id) setSelectedCollection('all');
      } catch (deleteError) {
        console.error('Error deleting collection:', deleteError);
        alert(`Failed to delete collection: ${deleteError.message || 'Unknown error'}`);
      }
    }
  };

  const handleActivateCamera = async (cameraId) => {
    if (!canManageCameraConfig) return;
    try {
      await activateCamera(cameraId);
      await initialize();
      setTimeout(() => window.dispatchEvent(new CustomEvent('refreshCameraStreams')), 1000);
    } catch (activationError) {
      console.error('Error activating camera:', activationError);
    }
  };

  const handleDeactivateCamera = async (cameraId) => {
    if (!canManageCameraConfig) return;
    try {
      await deactivateCamera(cameraId);
      await initialize();
    } catch (deactivationError) {
      console.error('Error deactivating camera:', deactivationError);
    }
  };

  const currentCameras = selectedCollection === 'all'
    ? cameras
    : getCamerasByCollection(selectedCollection);
  const activeCameras = currentCameras?.filter(camera => camera.is_active) || [];

  return (
    <div className="tabbed-camera-manager">
      <div className="manager-header">
        <div className="header-title">
          <Camera size={24} />
          <h2>{canManageCameraConfig ? 'Camera Management' : 'Assigned Cameras'}</h2>
        </div>
      </div>

      <div className="collection-selector">
        <label htmlFor="collection-select">Collection:</label>
        <select
          id="collection-select"
          value={selectedCollection}
          onChange={(e) => setSelectedCollection(e.target.value)}
          className="collection-dropdown"
        >
          <option value="all">All Collections</option>
          {collections?.map(collection => (
            <option key={collection.id} value={collection.id}>
              {collection.name} ({collection.camera_count || 0} cameras)
            </option>
          ))}
        </select>
        {canManageCameraConfig && (
          <>
            <button className="create-collection-btn" onClick={() => setShowCreateCollection(true)}>
              <Plus size={16} /> New Collection
            </button>
            <button
              className="edit-collection-btn"
              onClick={() => {
                const collection = collections?.find(c => c.id === selectedCollection);
                if (collection) handleEditCollection(collection);
                else alert('Please select a collection to edit');
              }}
              disabled={selectedCollection === 'all'}
            >
              Edit Collection
            </button>
          </>
        )}
      </div>

      {showCreateCollection && canManageCameraConfig && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Create New Collection</h3>
            <form onSubmit={handleCreateCollection}>
              <input
                type="text"
                value={newCollectionName}
                onChange={(e) => setNewCollectionName(e.target.value)}
                placeholder="Enter collection name"
                autoFocus
                required
              />
              <div className="modal-actions">
                <button type="submit" className="primary-btn">Create</button>
                <button type="button" className="secondary-btn" onClick={() => setShowCreateCollection(false)}>Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showEditCollection && editingCollection && canManageCameraConfig && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Edit Collection</h3>
            <form onSubmit={handleUpdateCollection}>
              <div className="form-group">
                <label htmlFor="edit-collection-name">Collection Name</label>
                <input
                  id="edit-collection-name"
                  type="text"
                  value={editCollectionName}
                  onChange={(e) => setEditCollectionName(e.target.value)}
                  placeholder="Enter collection name"
                  autoFocus
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="edit-collection-description">Description (Optional)</label>
                <textarea
                  id="edit-collection-description"
                  value={editCollectionDescription}
                  onChange={(e) => setEditCollectionDescription(e.target.value)}
                  placeholder="Enter description"
                  rows={3}
                />
              </div>
              <div className="modal-actions">
                <button type="submit" className="primary-btn">Update</button>
                {canDeleteCameraConfig && editingCollection.id !== 'default' && (
                  <button type="button" className="danger-btn" onClick={handleDeleteCollection}>Delete Collection</button>
                )}
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => {
                    setShowEditCollection(false);
                    setEditingCollection(null);
                    setEditCollectionName('');
                    setEditCollectionDescription('');
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="tab-navigation">
        {tabs.map(tab => {
          const IconComponent = tab.icon;
          return (
            <button
              key={tab.id}
              className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => handleTabChange(tab.id)}
            >
              <IconComponent size={18} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div className="tab-content">
        {error && <div className="error-banner"><p>Error: {error}</p></div>}

        {activeTab === 'cameras' && (
          <div className="cameras-tab">
            <div className="tab-header">
              <h3>
                Cameras in {selectedCollection === 'all' ? 'All Collections' :
                  collections?.find(c => c.id === selectedCollection)?.name || 'Unknown Collection'}
              </h3>
              <div className="camera-stats">
                <span className="stat">Total: {currentCameras?.length || 0}</span>
                <span className="stat active">Active: {activeCameras.length}</span>
              </div>
              {canManageCameraConfig && (
                <button className="add-camera-btn" onClick={handleAddCamera}>
                  <Plus size={16} /> Add Camera
                </button>
              )}
            </div>

            <div className="cameras-list">
              {currentCameras?.length === 0 ? (
                <div className="empty-state">
                  <Camera size={64} />
                  <h3>No cameras found</h3>
                  <p>{canManageCameraConfig ? 'Add your first camera to get started' : 'No cameras are assigned to your account.'}</p>
                  {canManageCameraConfig && (
                    <button className="primary-btn" onClick={handleAddCamera}>
                      <Plus size={16} /> Add Camera
                    </button>
                  )}
                </div>
              ) : (
                <div className="camera-table">
                  <div className="table-header">
                    <div className="col-name">Camera Name</div>
                    <div className="col-location">Location</div>
                    <div className="col-ip">IP Address</div>
                    <div className="col-status">Status</div>
                    {canManageCameraConfig && <div className="col-actions">Actions</div>}
                  </div>
                  {currentCameras?.map(camera => (
                    <div key={camera.id} className="table-row">
                      <div className="col-name"><div className="camera-name">{camera.name}</div></div>
                      <div className="col-location">{camera.location || 'Unknown'}</div>
                      <div className="col-ip">{camera.ip_address || '-'}</div>
                      <div className="col-status">
                        <span className={`status-badge ${camera.is_active ? 'active' : 'inactive'}`}>
                          {camera.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      {canManageCameraConfig && (
                        <div className="col-actions">
                          <button className="action-btn edit" onClick={() => handleEditCamera(camera)} title="Edit Camera">Edit</button>
                          <button
                            className="action-btn activate"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              if (camera.is_active) handleDeactivateCamera(camera.id);
                              else handleActivateCamera(camera.id);
                            }}
                            title={camera.is_active ? 'Deactivate' : 'Activate'}
                          >
                            {camera.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'add' && canManageCameraConfig && (
          <div className="add-camera-tab">
            <div className="tab-header"><h3>{editingCamera ? 'Edit Camera' : 'Add New Camera'}</h3></div>
            <div className="form-container">
              <AddCameraForm
                collectionId={selectedCollection !== 'all' ? selectedCollection : null}
                onClose={handleCloseCameraForm}
                editingCamera={editingCamera}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TabbedCameraManager;
