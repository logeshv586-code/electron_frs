import { create } from 'zustand';

export const useArchiveStore = create((set, get) => ({
  // State
  recordings: {},
  
  // Actions
  getRecordingStatus: (streamId) => {
    const { recordings } = get();
    return recordings[streamId] || { isRecording: false, duration: 0 };
  },
  
  setRecordingStatus: (streamId, status) => {
    set((state) => ({
      recordings: {
        ...state.recordings,
        [streamId]: status
      }
    }));
  },
  
  startRecording: (streamId) => {
    set((state) => ({
      recordings: {
        ...state.recordings,
        [streamId]: { isRecording: true, startTime: Date.now(), duration: 0 }
      }
    }));
  },
  
  stopRecording: (streamId) => {
    set((state) => ({
      recordings: {
        ...state.recordings,
        [streamId]: { isRecording: false, duration: 0 }
      }
    }));
  }
}));
