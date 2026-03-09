# Face Capture Implementation Guide

## Overview
This implementation adds automatic face capture functionality to the backend and provides FastAPI endpoints for manual capture requests from the Electron frontend.

## Files Created/Modified

### 1. **NEW: `backend_face/save_face.py`**
Core face-saving module with the following features:
- **Label sanitization**: Converts labels to safe filenames (e.g., "John Doe" → "john_doe")
- **Directory structure**:
  - Known faces: `captured_faces/known/<label>/`
  - Unknown faces: `captured_faces/unknown/`
- **Filename format**: `label_YYYYMMDD_HHMMSS_micros.jpg`
- **Rate-limiting**: 5-second minimum interval per label to prevent duplicate saves
- **CSV logging**: Logs to `captured_faces/capture_log.csv` with fields:
  - filename, label, timestamp_iso, saved_path, confidence, source
- **Thread-safe**: Uses locks for concurrent access

#### Key Functions:
```python
save_face_image(face_bgr, label, confidence=None, min_interval=5.0, source="stream") -> Optional[Path]
```

### 2. **MODIFIED: `backend_face/face_pipeline.py`**
Integrated automatic face capture into the detection loop:
- Imports `save_face_image` from `save_face.py`
- Spawns daemon threads to save detected faces asynchronously
- Prevents blocking of real-time frame processing
- Saves both "known" and "unknown" faces based on recognition results

**Key addition:**
```python
# After face recognition, spawn thread to save face
def _save_face_async():
    save_label = name if name != "Unknown" else "unknown"
    save_face_image(face_crop_bgr, label=save_label, confidence=conf, 
                   min_interval=MIN_SAVE_INTERVAL, source="stream")
save_thread = threading.Thread(target=_save_face_async, daemon=True)
save_thread.start()
```

### 3. **MODIFIED: `backend_face/main.py`**
Added two new FastAPI endpoints for manual face capture:

#### Endpoint 1: `/capture_face_upload` (POST)
Upload a face image file directly
```bash
curl -X POST http://192.168.1.209:8000/capture_face_upload \
  -F "file=@face.jpg" \
  -F "label=john" \
  -F "confidence=0.95"
```

Response:
```json
{
  "saved": true,
  "path": "C:\\python programs\\electron_frs\\backend_face\\captured_faces\\known\\john\\john_20251029_153012_123456.jpg",
  "label": "john",
  "source": "upload"
}
```

#### Endpoint 2: `/capture_face_b64` (POST)
Capture from base64 encoded image (typically from frontend video element)
```bash
curl -X POST http://192.168.1.209:8000/capture_face_b64 \
  -H "Content-Type: application/json" \
  -d '{
    "image_b64": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    "label": "alice",
    "confidence": 0.87
  }'
```

Response:
```json
{
  "saved": true,
  "path": "C:\\python programs\\electron_frs\\backend_face\\captured_faces\\known\\alice\\alice_20251029_153345_789123.jpg",
  "label": "alice",
  "source": "upload_b64"
}
```

## Features

### ✅ Automatic Capture
- Faces detected in real-time streams are automatically saved
- Async processing prevents frame rate degradation
- Rate-limiting prevents duplicate saves (5-second minimum per label)

### ✅ Manual Capture
- Frontend can request capture of current frame via `/capture_face_b64`
- Supports file upload via `/capture_face_upload`
- Both endpoints support optional confidence scores

### ✅ Organization
- Faces organized by label in `known/` subdirectories
- Unknown faces stored in `unknown/` directory
- Timestamps in filename ensure uniqueness
- Microsecond precision prevents collisions

### ✅ Logging
- CSV log tracks every save operation
- Records filename, label, timestamp, path, confidence, and source
- Useful for auditing and debugging

### ✅ Thread-Safe
- All operations use threading locks
- Safe for concurrent access from multiple detection threads
- Rate-limiting state protected by locks

## Usage Examples

### JavaScript/React Frontend - Capture from Video Element
```javascript
// Capture current frame from video stream
async function captureAndUpload(label = "unknown", confidence = null) {
  const video = document.getElementById("streamVideo");
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  
  const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
  
  const res = await fetch("http://192.168.1.209:8000/capture_face_b64", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      image_b64: dataUrl, 
      label: label,
      confidence: confidence 
    })
  });
  
  const result = await res.json();
  console.log("Capture result:", result);
  return result;
}
```

### File Structure After Captures
```
captured_faces/
├── capture_log.csv
├── known/
│   ├── alice/
│   │   ├── alice_20251029_153012_123456.jpg
│   │   ├── alice_20251029_160530_456789.jpg
│   │   └── ...
│   ├── bob/
│   │   └── bob_20251029_140000_111111.jpg
│   └── ...
└── unknown/
    ├── unknown_20251029_135522_222222.jpg
    └── ...
```

### CSV Log Format
```
filename,label,timestamp_iso,saved_path,confidence,source
alice_20251029_153012_123456.jpg,alice,2025-10-29T15:30:12.123456,C:\...\captured_faces\known\alice\alice_20251029_153012_123456.jpg,0.95,stream
bob_20251029_140000_111111.jpg,bob,2025-10-29T14:00:00.111111,C:\...\captured_faces\known\bob\bob_20251029_140000_111111.jpg,0.88,upload
unknown_20251029_135522_222222.jpg,unknown,2025-10-29T13:55:22.222222,C:\...\captured_faces\unknown\unknown_20251029_135522_222222.jpg,,stream
```

## Configuration

### Rate Limiting
- **Default**: 5 seconds per label
- **Location**: `backend_face/save_face.py` - `DEFAULT_MIN_SAVE_INTERVAL_SECONDS`
- **Override**: Pass `min_interval` parameter to `save_face_image()`

### Directories
- **Base**: `backend_face/captured_faces/`
- **Known**: `backend_face/captured_faces/known/<label>/`
- **Unknown**: `backend_face/captured_faces/unknown/`
- **Log**: `backend_face/captured_faces/capture_log.csv`

## Performance Considerations

1. **Async Threading**: Face saves happen in background threads, not blocking frame processing
2. **Rate Limiting**: Prevents storage bloat from redundant captures
3. **JPEG Quality**: 90% for manual captures, configurable per function call
4. **Thread Pool**: Uses daemon threads that clean up automatically

## Error Handling

- Invalid image formats: Returns 400 error with details
- File system errors: Logged to console, doesn't crash pipeline
- CSV logging failures: Graceful degradation, logged to console
- Rate-limited saves: Returns `None`, no error raised

## Integration Checklist

✅ `save_face.py` created with rate-limiting and CSV logging
✅ `face_pipeline.py` integrated automatic capture in detection loop
✅ `main.py` added `/capture_face_upload` endpoint
✅ `main.py` added `/capture_face_b64` endpoint
✅ All files compile without errors
✅ Thread-safe implementation with locks
✅ Proper label sanitization for filenames
✅ Automatic directory structure creation

## Troubleshooting

### Faces not being saved
1. Check if `captured_faces/` directory exists and is writable
2. Verify `face_pipeline.py` initialization completed (check logs)
3. Confirm faces are being detected (look for bounding boxes)
4. Check that rate-limiting isn't preventing saves (look at timestamps in CSV)

### CSV log not updating
1. Verify `captured_faces/` directory exists
2. Check file permissions on the directory
3. Look for "Failed to write capture log" messages in console

### Slow frame processing
- If frame rate drops, increase `MIN_SAVE_INTERVAL` in `face_pipeline.py`
- Or set `source="stream"` saves to use longer intervals

### Special characters in labels
- Labels are automatically sanitized (spaces → underscores, special chars removed)
- Check `capture_log.csv` for actual sanitized label used