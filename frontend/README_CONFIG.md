# Frontend Configuration Guide

## API URL Configuration

The frontend is now configured to work with both **192.168.1.209** (local development) and **server** (remote deployment).

### Default Behavior

- **Default**: `http://192.168.1.209:8005` (for local development)
- **Can be overridden** via environment variable

### Configuration Methods

#### Method 1: Environment Variable (Recommended)

Create a `.env` file in the `frontend` directory:

```bash
# For local development (default)
REACT_APP_API_BASE_URL=http://192.168.1.209:8005

# OR for server deployment
REACT_APP_API_BASE_URL=http://192.168.1.209:8005
```

#### Method 2: Set Before Running

**For React development server:**
```bash
# Local
REACT_APP_API_BASE_URL=localhost:8005 npm run react-dev

# Server
REACT_APP_API_BASE_URL=localhost:8005 npm run react-dev
```

**For Electron:**
```bash
# Local
API_BASE_URL=localhost:8005 npm start

# Server
API_BASE_URL=localhost:8005 npm start
```

### Usage Scenarios

#### Scenario 1: Local Development (Backend on same machine)
```bash
# 1. Start backend locally
cd backend_face
python start_server.py  # Runs on 192.168.1.209:8005

# 2. Start frontend (uses 192.168.1.209 by default)
cd frontend
npm run react-dev
npm run dev
```

#### Scenario 2: Remote Server (Backend on 192.168.1.209)
```bash
# 1. Backend is running on server 192.168.1.209:8005

# 2. Frontend connects to server
cd frontend
# Create .env file with:
echo "REACT_APP_API_BASE_URL=http://192.168.1.209:8005" > .env

# Or set before running:
REACT_APP_API_BASE_URL=localhost:8005 npm start
```

### Files Updated

All frontend components now use the centralized `apiConfig.js`:
- `src/utils/apiConfig.js` - Central configuration
- All components import from this file
- `main.js` (Electron) uses environment variable

### Verification

Check which URL is being used:
1. Open browser console
2. Look for API calls - they should show the configured URL
3. Or check: `console.log(API_BASE_URL)` in any component

### Troubleshooting

**If frontend can't connect:**
1. Check backend is running on the expected URL
2. Verify `.env` file exists and has correct URL
3. Restart React dev server after changing `.env`
4. Check browser console for connection errors

**For server deployment:**
- Make sure firewall allows connections to port 8005
- Verify backend CORS settings allow your frontend origin

