const { app, BrowserWindow, Menu, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const axios = require('axios');
const FormData = require('form-data');
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let AUTH_TOKEN = null;

axios.interceptors.request.use(
  function(config) {
    const url = config && config.url ? config.url : '';
    if (AUTH_TOKEN && url.includes('/api/')) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${AUTH_TOKEN}`;
    }
    return config;
  },
  function(error) {
    return Promise.reject(error);
  }
);

function loadEnvVariables() {
  try {
    const envPath = path.join(__dirname, '.env');
    if (fs.existsSync(envPath)) {
      const envContent = fs.readFileSync(envPath, 'utf-8');
      const lines = envContent.split('\n');
      for (const line of lines) {
        if (line && !line.startsWith('#')) {
          const [key, value] = line.split('=');
          if (key && value) {
            process.env[key.trim()] = value.trim();
          }
        }
      }
    }
  } catch (error) {
    console.error('Error loading .env file:', error);
  }
}

loadEnvVariables();

// API Base URL - defaults to 192.168.1.209, can be overridden via environment variable
const API_BASE_URL = process.env.API_BASE_URL || process.env.REACT_APP_API_BASE_URL || 'http://192.168.1.209:8005' || 'http://localhost:8005';
console.log('[Electron] API_BASE_URL configured as:', API_BASE_URL);

function loadFallbackPage(mainWindow) {
  const fallbackHtml = `
    <!DOCTYPE html>
    <html>
    <head>
      <title>Face Recognition System</title>
      <style>
        body { font-family: Arial, sans-serif; padding: 40px; text-align: center; }
        .error { color: #e74c3c; }
        .info { color: #3498db; }
      </style>
    </head>
    <body>
      <h1>Face Recognition System</h1>
      <div class="error">
        <h2>Build files not found</h2>
        <p>Please run the following commands to build the application:</p>
        <pre>npm run build</pre>
        <p>Then restart the application.</p>
      </div>
      <div class="info">
        <p>Backend Status: <span id="backend-status">Checking...</span></p>
      </div>
      <script>
        // Check backend status
        fetch('` + API_BASE_URL + `/health')
          .then(() => {
            document.getElementById('backend-status').textContent = 'Running ✅';
            document.getElementById('backend-status').style.color = '#27ae60';
          })
          .catch(() => {
            document.getElementById('backend-status').textContent = 'Not Running ❌';
            document.getElementById('backend-status').style.color = '#e74c3c';
          });
      </script>
    </body>
    </html>
  `;

  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml)}`);
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      enableRemoteModule: false,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, 'assets/icon.png'), // Add your app icon
    titleBarStyle: 'default',
    show: false
  });

  // Clear cache to ensure fresh load
  mainWindow.webContents.session.clearCache();

  // Create application menu
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Refresh',
          accelerator: 'CmdOrCtrl+R',
          click: () => {
            mainWindow.reload();
          }
        },
        {
          label: 'Exit',
          accelerator: process.platform === 'darwin' ? 'Cmd+Q' : 'Ctrl+Q',
          click: () => {
            app.quit();
          }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        {
          label: 'Toggle Developer Tools',
          accelerator: process.platform === 'darwin' ? 'Alt+Cmd+I' : 'Ctrl+Shift+I',
          click: () => {
            mainWindow.webContents.toggleDevTools();
          }
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Load the app
  if (isDev) {
    // In development, try to load from development server first
    mainWindow.loadURL('http://localhost:3000')
      .then(() => {
        console.log('Loaded development server');
      })
      .catch((err) => {
        console.log('Failed to load dev server:', err.message);
        // If dev server is not running, fall back to build
        const buildPath = path.join(__dirname, 'build/index.html');
        if (fs.existsSync(buildPath)) {
          console.log('Falling back to build:', buildPath);
          mainWindow.loadFile(buildPath);
        } else {
          // Show fallback page
          console.log('No build found, showing fallback page');
          loadFallbackPage(mainWindow);
        }
      });
    // Open dev tools in development mode
    mainWindow.webContents.openDevTools();
  } else {
    // In production, load from build directory
    const buildPath = path.join(__dirname, 'build/index.html');
    if (fs.existsSync(buildPath)) {
      mainWindow.loadFile(buildPath);
    } else {
      // Show fallback page
      loadFallbackPage(mainWindow);
    }
  }
}

// IPC Handlers for Video Processing
ipcMain.handle('set-auth-token', async (event, token) => {
  AUTH_TOKEN = token || null;
  if (AUTH_TOKEN) {
    axios.defaults.headers.common = axios.defaults.headers.common || {};
    axios.defaults.headers.common['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  } else {
    if (axios.defaults.headers.common) {
      delete axios.defaults.headers.common['Authorization'];
    }
  }
  return { success: true };
});

ipcMain.handle('clear-auth-token', async () => {
  AUTH_TOKEN = null;
  if (axios.defaults.headers.common) {
    delete axios.defaults.headers.common['Authorization'];
  }
  return { success: true };
});

ipcMain.handle('check-backend-status', async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/status`, { timeout: 5000 });
    return {
      success: true,
      success: true,
      available: true,
      status: response.data
    };
  } catch (error) {
    return {
      success: false,
      available: false,
      error: error.message
    };
  }
});

ipcMain.handle('select-video-file', async () => {
  try {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: [
        { name: 'Video Files', extensions: ['mp4', 'avi', 'mov', 'mkv', 'wmv'] }
      ]
    });

    if (result.canceled) {
      return { success: false };
    }

    return {
      success: true,
      filePath: result.filePaths[0]
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('upload-video', async (event, filePath) => {
  try {
    const formData = new FormData();
    formData.append('video', fs.createReadStream(filePath));

    const response = await axios.post(`${API_BASE_URL}/api/video/upload`, formData, {
      headers: formData.getHeaders(),
      timeout: 30000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('start-processing', async (event, videoId, options) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/video/process/${videoId}`, options, {
      timeout: 10000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-process-status', async (event, taskId) => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/video/status/${taskId}`, {
      timeout: 5000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-process-result', async (event, taskId) => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/video/result/${taskId}`, {
      timeout: 10000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('cancel-processing', async (event, taskId) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/video/cancel/${taskId}`, {}, {
      timeout: 5000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('delete-video', async (event, videoId) => {
  try {
    const response = await axios.delete(`${API_BASE_URL}/api/video/${videoId}`, {
      timeout: 5000
    });

    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// IPC Handlers for Enhanced Camera Management
ipcMain.handle('get-camera-list', async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/collections/cameras`, { timeout: 5000 });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('add-camera', async (event, config) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras`, {
      name: config.name || 'Camera',
      rtsp_url: config.rtsp_url,
      collection_id: config.collection_id || 'default'
    }, {
      timeout: 10000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('remove-camera', async (event, cameraId) => {
  try {
    const response = await axios.delete(`${API_BASE_URL}/api/collections/cameras/${cameraId}`, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('validate-camera', async (event, validationData) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/validate-camera`, validationData, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// Enhanced camera activation/deactivation
ipcMain.handle('activate-camera', async (event, cameraId) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras/${cameraId}/activate`, {}, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('deactivate-camera', async (event, cameraId) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras/${cameraId}/deactivate`, {}, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-camera-frame', async (event, cameraId) => {
  try {
    // Get camera stream URL for frame retrieval
    const response = await axios.get(`${API_BASE_URL}/api/collections/cameras/${cameraId}/stream`, {
      timeout: 5000,
      responseType: 'stream'
    });
    return {
      success: true,
      streamUrl: `${API_BASE_URL}/api/collections/cameras/${cameraId}/stream`
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// New streaming handlers
ipcMain.handle('start-camera-stream', async (event, cameraId) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras/${cameraId}/start-stream`, {}, {
      timeout: 10000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('stop-camera-stream', async (event, cameraId) => {
  try {
    const response = await axios.delete(`${API_BASE_URL}/api/collections/cameras/${cameraId}/stop-stream`, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// Recording handlers
ipcMain.handle('start-camera-recording', async (event, cameraId, durationMinutes) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras/${cameraId}/start-recording`, {
      duration_minutes: durationMinutes
    }, {
      timeout: 10000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('stop-camera-recording', async (event, cameraId, recordingId) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/collections/cameras/${cameraId}/stop-recording/${recordingId}`, {}, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-camera-recordings', async (event, cameraId) => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/collections/cameras/${cameraId}/recordings`, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-active-recordings', async (event) => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/collections/recordings/active`, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('get-camera-status', async (event, cameraId) => {
  try {
    // Get camera status from the enhanced system
    const response = await axios.get(`${API_BASE_URL}/api/collections/cameras/${cameraId}`, {
      timeout: 5000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// IPC Handlers for Registration
ipcMain.handle('register-single', async (event, formData) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/registration/single`, formData, {
      headers: formData.getHeaders ? formData.getHeaders() : { 'Content-Type': 'multipart/form-data' },
      timeout: 30000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('register-bulk', async (event, excelBuffer, imageFileInfos) => {
  const FormDataLocal = require('form-data');
  let tempExcelPath = null;
  
  try {
    const os = require('os');
    const formData = new FormDataLocal();
    
    tempExcelPath = path.join(os.tmpdir(), `temp_excel_${Date.now()}.xlsx`);
    const bufferData = Buffer.from(excelBuffer);
    fs.writeFileSync(tempExcelPath, bufferData);
    
    formData.append('excel_file', fs.createReadStream(tempExcelPath), 'data.xlsx');
    
    for (const fileInfo of imageFileInfos) {
      if (fs.existsSync(fileInfo.fullPath)) {
        const stream = fs.createReadStream(fileInfo.fullPath);
        formData.append('image_files', stream, fileInfo.relativePath);
      }
    }
    
    const response = await axios.post(`${API_BASE_URL}/api/registration/register/bulk`, formData, {
      headers: formData.getHeaders(),
      timeout: 60000
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    console.error('Bulk registration error:', error);
    return {
      success: false,
      error: error.message
    };
  } finally {
    if (tempExcelPath) {
      try {
        fs.unlinkSync(tempExcelPath);
      } catch (e) {
        console.error('Error deleting temp Excel file:', e);
      }
    }
  }
});

ipcMain.handle('get-registered-faces', async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/registration/gallery`, {
      timeout: 10000
    });
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// IPC Handlers for File Operations
ipcMain.handle('select-file', async (event, options = {}) => {
  try {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: options.filters || [
        { name: 'All Files', extensions: ['*'] }
      ]
    });

    if (result.canceled) {
      return { success: false };
    }

    return {
      success: true,
      filePath: result.filePaths[0]
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('select-folder', async () => {
  try {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory']
    });

    if (result.canceled) {
      return { success: false };
    }

    return {
      success: true,
      folderPath: result.filePaths[0]
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('scan-folder-for-images', async (event, folderPath) => {
  try {
    const validExtensions = ['.jpg', '.jpeg', '.png'];
    const files = [];

    const scanDirectory = (dirPath, relativePrefix = '') => {
      try {
        const entries = fs.readdirSync(dirPath, { withFileTypes: true });
        
        for (const entry of entries) {
          const fullPath = path.join(dirPath, entry.name);
          const relativePath = path.join(relativePrefix, entry.name);
          
          if (entry.isDirectory()) {
            scanDirectory(fullPath, relativePath);
          } else if (entry.isFile()) {
            const ext = path.extname(entry.name).toLowerCase();
            if (validExtensions.includes(ext)) {
              files.push({
                fullPath: fullPath,
                relativePath: relativePath
              });
            }
          }
        }
      } catch (error) {
        console.error(`Error scanning directory ${dirPath}:`, error);
      }
    };

    scanDirectory(folderPath);
    
    return {
      success: true,
      files: files,
      count: files.length
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// IPC Handlers for Utility Functions
ipcMain.handle('show-message-box', async (event, options) => {
  try {
    const result = await dialog.showMessageBox(options);
    return {
      success: true,
      response: result.response,
      checkboxChecked: result.checkboxChecked
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

ipcMain.handle('show-error-dialog', async (event, title, content) => {
  try {
    await dialog.showErrorBox(title, content);
    return { success: true };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
});

// Optimize GPU usage for animations
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('ignore-gpu-blacklist');
app.commandLine.appendSwitch('disable-gpu-vsync'); /* Optional: might help if vsync is causing stutter */

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
