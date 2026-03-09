# Face Recognition System - Frontend

A React.js Electron desktop application for face recognition with backend connectivity.

## Features

- **Gallery View**: Browse registered faces with their details (name, age, gender, category)
- **Face Events**: View face detection events from cameras with filtering options
- **Find Occurrence**: Upload an image to find matching faces in the database
- **Real-time Backend Connectivity**: Connects to FastAPI backend on port 8000

## Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- Backend server running on http://192.168.1.209:8000

## Installation

1. Install dependencies:
```bash
npm install
```

## Running the Application

### Development Mode

1. Start the backend server first (from the backend_face directory):
```bash
cd ../backend_face
python main.py
```

2. Start the React development server:
```bash
npm run react-dev
```

3. In another terminal, start the Electron app:
```bash
npm run dev
```

### Production Mode

1. Build the React app:
```bash
npm run build
```

2. Start the Electron app:
```bash
npm start
```

## Available Scripts

- `npm run react-dev` - Start React development server
- `npm run dev` - Start Electron in development mode (requires React dev server)
- `npm start` - Start Electron in production mode
- `npm run build` - Build React app for production
- `npm run electron-pack` - Package Electron app for distribution

## API Endpoints Used

- `GET /api/registration/gallery` - Get gallery data
- `GET /api/events/cameras` - Get available cameras
- `GET /api/events/filter` - Filter face events
- `POST /api/events/match-face` - Find matching faces

## Troubleshooting

### Backend Connection Issues

1. Ensure the backend server is running on http://192.168.1.209:8000
2. Check if CORS is properly configured in the backend
3. Verify the API endpoints are accessible

### Image Loading Issues

- Images are loaded using `file://` protocol for local file access
- Ensure image paths are correct and files exist
- Check browser console for image loading errors

### Electron Issues

- Make sure both React dev server (port 3000) and backend (port 8000) are running
- Check Electron console for any JavaScript errors
- Verify NODE_ENV is set correctly for development mode

## File Structure

```
frontend/
├── public/
│   ├── index.html
│   └── manifest.json
├── src/
│   ├── components/
│   │   ├── FaceGallery.js
│   │   ├── FaceGallery.css
│   │   ├── PersonCard.js
│   │   ├── PersonCard.css
│   │   ├── EventsWidget.js
│   │   ├── EventsWidget.css
│   │   ├── FaceEvents.js
│   │   ├── FaceEvents.css
│   │   ├── FaceCard.js
│   │   ├── FaceCard.css
│   │   ├── FindOccurrence.js
│   │   └── FindOccurrence.css
│   ├── App.js
│   ├── App.css
│   ├── index.js
│   └── index.css
├── main.js (Electron main process)
├── package.json
└── README.md
```

## Error Handling

The application includes comprehensive error handling for:
- Network connectivity issues
- Backend server unavailability
- Invalid API responses
- Image loading failures
- File upload errors

All errors are displayed to the user with helpful messages and retry options.
