const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  setAuthToken: (token) => ipcRenderer.invoke('set-auth-token', token),
  clearAuthToken: () => ipcRenderer.invoke('clear-auth-token'),
  // Video processing APIs
  checkBackendStatus: () => ipcRenderer.invoke('check-backend-status'),
  selectVideoFile: () => ipcRenderer.invoke('select-video-file'),
  uploadVideo: (filePath) => ipcRenderer.invoke('upload-video', filePath),
  startProcessing: (videoId, options) => ipcRenderer.invoke('start-processing', videoId, options),
  getProcessStatus: (taskId) => ipcRenderer.invoke('get-process-status', taskId),
  getProcessResult: (taskId) => ipcRenderer.invoke('get-process-result', taskId),
  cancelProcessing: (taskId) => ipcRenderer.invoke('cancel-processing', taskId),
  deleteVideo: (videoId) => ipcRenderer.invoke('delete-video', videoId),
  
  // Camera management APIs
  getCameraList: () => ipcRenderer.invoke('get-camera-list'),
  addCamera: (config) => ipcRenderer.invoke('add-camera', config),
  removeCamera: (cameraId) => ipcRenderer.invoke('remove-camera', cameraId),
  activateCamera: (cameraId) => ipcRenderer.invoke('activate-camera', cameraId),
  deactivateCamera: (cameraId) => ipcRenderer.invoke('deactivate-camera', cameraId),
  getCameraFrame: (cameraId) => ipcRenderer.invoke('get-camera-frame', cameraId),
  getCameraStatus: (cameraId) => ipcRenderer.invoke('get-camera-status', cameraId),
  startCameraStream: (cameraId) => ipcRenderer.invoke('start-camera-stream', cameraId),
  stopCameraStream: (cameraId) => ipcRenderer.invoke('stop-camera-stream', cameraId),

  // Recording APIs
  startCameraRecording: (cameraId, durationMinutes) => ipcRenderer.invoke('start-camera-recording', cameraId, durationMinutes),
  stopCameraRecording: (cameraId, recordingId) => ipcRenderer.invoke('stop-camera-recording', cameraId, recordingId),
  getCameraRecordings: (cameraId) => ipcRenderer.invoke('get-camera-recordings', cameraId),
  getActiveRecordings: () => ipcRenderer.invoke('get-active-recordings'),
  
  // Registration APIs
  registerSingle: (formData) => ipcRenderer.invoke('register-single', formData),
  registerBulk: (excelFile, imageFileInfos) => ipcRenderer.invoke('register-bulk', excelFile, imageFileInfos),
  getRegisteredFaces: () => ipcRenderer.invoke('get-registered-faces'),
  
  // File system APIs
  selectFile: (options) => ipcRenderer.invoke('select-file', options),
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  scanFolderForImages: (folderPath) => ipcRenderer.invoke('scan-folder-for-images', folderPath),
  
  // Utility APIs
  showMessageBox: (options) => ipcRenderer.invoke('show-message-box', options),
  showErrorDialog: (title, content) => ipcRenderer.invoke('show-error-dialog', title, content),
  
  // Platform info
  platform: process.platform,
  
  // Event listeners
  onWindowClose: (callback) => ipcRenderer.on('window-close', callback),
  removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});

// Log that preload script has loaded
console.log('Preload script loaded successfully');
