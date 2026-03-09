# Environment Variable Setup Guide

## Quick Setup for Server Deployment

### Method 1: Create `.env` File (Recommended)

Create a file named `.env` in the `frontend` directory:

```bash
cd frontend
```

**For Windows (PowerShell or CMD):**
```bash
echo REACT_APP_API_BASE_URL=localhost:8005 > .env
```

**For Linux/Mac:**
```bash
echo "REACT_APP_API_BASE_URL=http://192.168.1.209:8005" > .env
```

**Or manually create `.env` file with this content:**
```
REACT_APP_API_BASE_URL=http://192.168.1.209:8005
```

### Method 2: Set Environment Variable Before Running

**For React Development Server:**
```bash
# Windows (PowerShell)
$env:REACT_APP_API_BASE_URL="http://192.168.1.209:8005"; npm run react-dev

# Windows (CMD)
set REACT_APP_API_BASE_URL=localhost:8005 && npm run react-dev

# Linux/Mac
REACT_APP_API_BASE_URL=localhost:8005 npm run react-dev
```

**For Electron (Production):**
```bash
# Windows (PowerShell)
$env:REACT_APP_API_BASE_URL="http://192.168.1.209:8005"; npm start

# Windows (CMD)
set REACT_APP_API_BASE_URL=localhost:8005 && npm start

# Linux/Mac
REACT_APP_API_BASE_URL=localhost:8005 npm start
```

### Method 3: Set System-Wide Environment Variable (Windows)

1. Open **System Properties**:
   - Press `Win + R`, type `sysdm.cpl`, press Enter
   - Or: Right-click "This PC" → Properties → Advanced system settings

2. Click **Environment Variables**

3. Under **User variables**, click **New**

4. Add:
   - Variable name: `REACT_APP_API_BASE_URL`
   - Variable value: `http://192.168.1.209:8005`

5. Click **OK** on all dialogs

6. **Restart your terminal/IDE** for changes to take effect

### Method 4: Set System-Wide Environment Variable (Linux/Mac)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
echo 'export REACT_APP_API_BASE_URL=http://192.168.1.209:8005' >> ~/.bashrc
source ~/.bashrc
```

## For Backend (Server Side)

On the server machine (192.168.1.209), set the environment variable:

```bash
# Linux/Mac
export API_BASE_URL=http://192.168.1.209:8005

# Make it permanent
echo 'export API_BASE_URL=http://192.168.1.209:8005' >> ~/.bashrc
source ~/.bashrc
```

Then start the backend:
```bash
cd /home/eagle/FRS/backend_face
source /home/eagle/face_match/pyqt_env/bin/activate
python start_server.py
```

## Verification

### Check if Environment Variable is Set

**Windows (PowerShell):**
```powershell
echo $env:REACT_APP_API_BASE_URL
```

**Windows (CMD):**
```cmd
echo %REACT_APP_API_BASE_URL%
```

**Linux/Mac:**
```bash
echo $REACT_APP_API_BASE_URL
```

### Test in Application

1. Start the frontend
2. Open browser console (F12)
3. Check network requests - they should show `http://192.168.1.209:8005`
4. Or add temporary console log:
   ```javascript
   console.log('API URL:', process.env.REACT_APP_API_BASE_URL || 'http://192.168.1.209:8005');
   ```

## Important Notes

1. **`.env` file location**: Must be in the `frontend` directory (same level as `package.json`)

2. **Restart required**: After creating/modifying `.env` file, you must:
   - Stop the React dev server (Ctrl+C)
   - Restart it: `npm run react-dev`

3. **Build process**: If you build the app (`npm run build`), the environment variable is baked into the build. You'll need to rebuild if you change it.

4. **File format**: `.env` file should NOT have quotes around values:
   ```
   ✅ Correct: REACT_APP_API_BASE_URL=http://192.168.1.209:8005
   ❌ Wrong: REACT_APP_API_BASE_URL="http://192.168.1.209:8005"
   ```

5. **Git ignore**: The `.env` file should be in `.gitignore` (already configured) so it won't be committed to git.

## Quick Reference

| Scenario | Frontend Command | Backend Command |
|----------|-----------------|-----------------|
| **Local Development** | No env var needed (defaults to 192.168.1.209) | No env var needed |
| **Server Deployment** | Set `REACT_APP_API_BASE_URL=http://192.168.1.209:8005` | Set `API_BASE_URL=http://192.168.1.209:8005` |

## Troubleshooting

**If environment variable is not working:**

1. Check `.env` file exists in `frontend/` directory
2. Check file has correct format (no quotes, no spaces)
3. Restart React dev server
4. Check console for the actual URL being used
5. Verify variable name: `REACT_APP_API_BASE_URL` (must start with `REACT_APP_`)


