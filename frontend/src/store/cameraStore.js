import { create } from 'zustand';
import { extractIPFromStreamURL } from '../utils/ipValidation';
import useAuthStore from './authStore';

// Import from centralized config
import { API_BASE_URL } from '../utils/apiConfig';

export const useCameraStore = create((set, get) => ({
  // State
  cameras: [],
  collections: [],
  activeCollection: 'default',
  loading: false,
  error: null,
  currentPage: 1,
  totalPages: 1,
  totalCameras: 0,
  activeCameras: 0,
  bookmarkedCameras: new Set(), // Store bookmarked camera IDs

  // Actions
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  clearError: () => set({ error: null }),

  // Fetch cameras with pagination
  fetchCameras: async (page = 1) => {
    const { token } = useAuthStore.getState();
    set({ loading: true, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras?page=${page}&per_page=6`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      
      set({
        cameras: data.cameras || [],
        collections: data.collections || [],
        currentPage: data.current_page || 1,
        totalPages: data.total_pages || 1,
        totalCameras: data.total_cameras || 0,
        activeCameras: data.active_cameras || 0,
        loading: false
      });
    } catch (error) {
      console.error('Error fetching cameras:', error);
      set({ 
        error: 'Failed to load cameras. Please check your connection and try again.',
        loading: false 
      });
    }
  },

  // Add new camera
  addCamera: async (name, streamUrl, collectionId = null, location = '') => {
    const { token } = useAuthStore.getState();
    set({ loading: true, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          name: name.trim(),
          rtsp_url: streamUrl.trim(),
          collection_id: collectionId || 'default',
          location: location.trim()
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      
      if (!result.success) {
        throw new Error(result.error || 'Failed to add camera');
      }

      // Refresh cameras list
      await get().fetchCameras(get().currentPage);
      
      set({ loading: false });
      return result;
    } catch (error) {
      console.error('Error adding camera:', error);
      const errorMessage = error.message || 'Failed to add camera. Please try again.';
      set({ error: errorMessage, loading: false });
      throw error;
    }
  },

  // Update camera
  updateCamera: async (cameraId, updates) => {
    const { token } = useAuthStore.getState();
    set({ loading: true, error: null });
    try {
      // Map frontend field names to backend field names
      const backendUpdates = {
        ...updates,
        rtsp_url: updates.streamUrl || updates.rtsp_url,
        collection_id: updates.collectionId || updates.collection_id
      };
      
      // Remove frontend-only fields
      delete backendUpdates.streamUrl;
      delete backendUpdates.collectionId;
      
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras/${cameraId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(backendUpdates),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      
      if (!result.success) {
        throw new Error(result.error || 'Failed to update camera');
      }

      // Refresh cameras list
      await get().fetchCameras(get().currentPage);
      
      set({ loading: false });
      return result;
    } catch (error) {
      console.error('Error updating camera:', error);
      const errorMessage = error.message || 'Failed to update camera. Please try again.';
      set({ error: errorMessage, loading: false });
      throw error;
    }
  },

  // Remove camera
  removeCamera: async (cameraId) => {
    const { token } = useAuthStore.getState();
    set({ loading: true, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras/${cameraId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      
      if (!result.success) {
        throw new Error(result.error || 'Failed to remove camera');
      }

      // Refresh cameras list
      await get().fetchCameras(get().currentPage);
      
      set({ loading: false });
      return result;
    } catch (error) {
      console.error('Error removing camera:', error);
      const errorMessage = error.message || 'Failed to remove camera. Please try again.';
      set({ error: errorMessage, loading: false });
      throw error;
    }
  },

  // Validate camera data
  validateCamera: async (ip, streamUrl, collectionName = null, excludeIp = null) => {
    const { token } = useAuthStore.getState();
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/validate-camera`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          ip,
          streamUrl,
          collection_name: collectionName,
          exclude_ip: excludeIp
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Validation error:', error);
      return {
        valid: false,
        error: 'Failed to validate camera data. Please try again.',
        type: 'network_error'
      };
    }
  },

  // Set active collection
  setActiveCollection: (collectionId) => {
    set({ activeCollection: collectionId });
  },

  // Get camera by ID
  getCameraById: (cameraId) => {
    const { cameras } = get();
    return cameras.find(camera => camera.id === cameraId);
  },

  // Get cameras by collection
  getCamerasByCollection: (collectionId) => {
    const { cameras } = get();
    return cameras.filter(camera => {
      // Handle different possible collection property names
      const cameraCollectionId = camera.collection_id || camera.collectionId || camera.collection;
      return cameraCollectionId === collectionId;
    });
  },

  // Pagination
  goToPage: async (page) => {
    if (page >= 1 && page <= get().totalPages) {
      await get().fetchCameras(page);
    }
  },

  nextPage: async () => {
    const { currentPage, totalPages } = get();
    if (currentPage < totalPages) {
      await get().fetchCameras(currentPage + 1);
    }
  },

  previousPage: async () => {
    const { currentPage } = get();
    if (currentPage > 1) {
      await get().fetchCameras(currentPage - 1);
    }
  },

  // Collection management
  createCollection: async (name, description = null) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name,
          description
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const errorMessage = errorData.detail || errorData.message || 'Failed to create collection';
        throw new Error(errorMessage);
      }

      const result = await response.json();
      
      // Refresh collections
      await get().fetchCameras(get().currentPage);
      
      return result.collection.id;
    } catch (error) {
      console.error('Error creating collection:', error);
      throw error;
    }
  },

  renameCollection: async (collectionId, newName) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newName
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const errorMessage = errorData.detail || errorData.message || 'Failed to rename collection';
        throw new Error(errorMessage);
      }

      const result = await response.json();
      
      // Refresh collections
      await get().fetchCameras(get().currentPage);
      
      return result;
    } catch (error) {
      console.error('Error renaming collection:', error);
      throw error;
    }
  },

  updateCollection: async (collectionId, updates) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updates),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const errorMessage = errorData.detail || errorData.message || 'Failed to update collection';
        throw new Error(errorMessage);
      }

      const result = await response.json();
      
      // Refresh collections
      await get().fetchCameras(get().currentPage);
      
      return result;
    } catch (error) {
      console.error('Error updating collection:', error);
      throw error;
    }
  },

  deleteCollection: async (collectionId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const errorMessage = errorData.detail || errorData.message || 'Failed to delete collection';
        throw new Error(errorMessage);
      }

      const result = await response.json();
      
      // Refresh collections
      await get().fetchCameras(get().currentPage);
      
      // If the deleted collection was selected, switch to 'all'
      if (get().activeCollection === collectionId) {
        set({ activeCollection: 'default' });
      }
      
      return result;
    } catch (error) {
      console.error('Error deleting collection:', error);
      throw error;
    }
  },

  addCameraToCollection: async (cameraId, collectionId) => {
    try {
      await get().updateCamera(cameraId, { collection_id: collectionId });
    } catch (error) {
      console.error('Error adding camera to collection:', error);
      throw error;
    }
  },

  removeCameraFromCollection: async (cameraId) => {
    try {
      await get().removeCamera(cameraId);
    } catch (error) {
      console.error('Error removing camera from collection:', error);
      throw error;
    }
  },

  setCollectionActive: (collectionId) => {
    set({ activeCollection: collectionId });
  },

  // Bookmark management
  isBookmarked: (cameraId) => {
    const { bookmarkedCameras } = get();
    return bookmarkedCameras.has(cameraId);
  },

  toggleBookmark: (cameraId) => {
    set(state => {
      const newBookmarkedCameras = new Set(state.bookmarkedCameras);
      if (newBookmarkedCameras.has(cameraId)) {
        newBookmarkedCameras.delete(cameraId);
      } else {
        newBookmarkedCameras.add(cameraId);
      }
      return { bookmarkedCameras: newBookmarkedCameras };
    });
  },

  getBookmarkedCameras: () => {
    const { cameras, bookmarkedCameras } = get();
    return cameras.filter(camera => bookmarkedCameras.has(camera.id));
  },

  // Camera activation/deactivation
  activateCamera: async (cameraId) => {
    console.log('activateCamera called with cameraId:', cameraId);
    set({ loading: true, error: null });
    try {
      const url = `${API_BASE_URL}/api/collections/cameras/${cameraId}/activate`;
      console.log('Making request to:', url);

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      console.log('Response status:', response.status);
      console.log('Response ok:', response.ok);

      if (!response.ok) {
        const errorData = await response.json();
        console.error('Error response data:', errorData);
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      console.log('Activation result:', result);

      if (!result.success) {
        throw new Error(result.error || 'Failed to activate camera');
      }

      // Update the camera in the local state
      set(state => ({
        cameras: state.cameras.map(camera =>
          camera.id === cameraId
            ? { ...camera, is_active: true, status: 'active' }
            : camera
        ),
        loading: false
      }));

      console.log('Camera activation successful');
      return result;
    } catch (error) {
      console.error('Error activating camera:', error);
      set({
        error: error.message || 'Failed to activate camera',
        loading: false
      });
      throw error;
    }
  },

  deactivateCamera: async (cameraId) => {
    set({ loading: true, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras/${cameraId}/deactivate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Failed to deactivate camera');
      }

      // Update the camera in the local state
      set(state => ({
        cameras: state.cameras.map(camera =>
          camera.id === cameraId
            ? { ...camera, is_active: false, status: 'inactive' }
            : camera
        ),
        loading: false
      }));

      return result;
    } catch (error) {
      console.error('Error deactivating camera:', error);
      set({
        error: error.message || 'Failed to deactivate camera',
        loading: false
      });
      throw error;
    }
  },

  // Initialize store
  initialize: async () => {
    await get().fetchCameras(1);
  }
}));
