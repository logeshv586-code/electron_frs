/**
 * Frontend Face Capture Examples for Electron/React
 * 
 * These functions demonstrate how to integrate the new face capture endpoints
 * into your Electron/React frontend application.
 */

// ============== EXAMPLE 1: Capture from Video Element ==============

/**
 * Capture current frame from a video stream and send to backend
 * @param {string} videoElementId - ID of the video HTML element
 * @param {string} label - Person name/label (default: "unknown")
 * @param {number} confidence - Optional confidence score (0.0-1.0)
 * @returns {Promise<Object>} - Result from backend
 */
async function captureFromVideoStream(videoElementId = "streamVideo", label = "unknown", confidence = null) {
  try {
    const video = document.getElementById(videoElementId);
    if (!video) {
      console.error(`Video element with ID "${videoElementId}" not found`);
      return null;
    }

    // Create canvas from video frame
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    
    // Convert to base64 JPEG
    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    
    // Send to backend
    const payload = {
      image_b64: dataUrl,
      label: label,
      confidence: confidence
    };

    console.log(`Capturing face for label: ${label}, confidence: ${confidence}`);
    
    const response = await fetch("http://192.168.1.209:8000/capture_face_b64", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const error = await response.json();
      console.error("Capture failed:", error);
      return null;
    }

    const result = await response.json();
    console.log("Capture successful:", result);
    return result;
  } catch (error) {
    console.error("Error capturing face:", error);
    return null;
  }
}

// ============== EXAMPLE 2: Upload Face Image File ==============

/**
 * Upload a face image file from file input
 * @param {HTMLInputElement} fileInput - File input element
 * @param {string} label - Person name/label (default: "unknown")
 * @param {number} confidence - Optional confidence score
 * @returns {Promise<Object>} - Result from backend
 */
async function uploadFaceImage(fileInput, label = "unknown", confidence = null) {
  try {
    if (!fileInput.files || fileInput.files.length === 0) {
      console.error("No file selected");
      return null;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);
    formData.append("label", label);
    if (confidence !== null) {
      formData.append("confidence", confidence);
    }

    console.log(`Uploading face image: ${file.name}, label: ${label}`);

    const response = await fetch("http://192.168.1.209:8000/capture_face_upload", {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      const error = await response.json();
      console.error("Upload failed:", error);
      return null;
    }

    const result = await response.json();
    console.log("Upload successful:", result);
    return result;
  } catch (error) {
    console.error("Error uploading face:", error);
    return null;
  }
}

// ============== EXAMPLE 3: React Component ==============

/**
 * React component for face capture
 */
const FaceCaptureComponent = () => {
  const [label, setLabel] = React.useState("unknown");
  const [confidence, setConfidence] = React.useState(0.95);
  const [capturing, setCapturing] = React.useState(false);
  const [lastResult, setLastResult] = React.useState(null);
  const videoRef = React.useRef(null);
  const fileInputRef = React.useRef(null);

  // Handler for capture button
  const handleCapture = async () => {
    setCapturing(true);
    try {
      const result = await captureFromVideoStream("streamVideo", label, confidence);
      setLastResult(result);
      if (result?.saved) {
        alert(`Face saved successfully!\nPath: ${result.path}`);
      } else {
        alert("Failed to save face - might be rate-limited");
      }
    } finally {
      setCapturing(false);
    }
  };

  // Handler for file upload
  const handleFileUpload = async () => {
    setCapturing(true);
    try {
      const result = await uploadFaceImage(fileInputRef.current, label, confidence);
      setLastResult(result);
      if (result?.saved) {
        alert(`Face uploaded successfully!\nPath: ${result.path}`);
      } else {
        alert("Failed to upload face");
      }
    } finally {
      setCapturing(false);
    }
  };

  return (
    <div style={{ padding: "20px", border: "1px solid #ccc", borderRadius: "8px" }}>
      <h2>Face Capture</h2>
      
      <div style={{ marginBottom: "10px" }}>
        <label>
          Person Label:
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Enter person name or 'unknown'"
            style={{ marginLeft: "10px", padding: "5px" }}
          />
        </label>
      </div>

      <div style={{ marginBottom: "10px" }}>
        <label>
          Confidence (0.0-1.0):
          <input
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={confidence}
            onChange={(e) => setConfidence(parseFloat(e.target.value))}
            style={{ marginLeft: "10px", padding: "5px", width: "100px" }}
          />
        </label>
      </div>

      <div style={{ marginBottom: "15px" }}>
        <button
          onClick={handleCapture}
          disabled={capturing}
          style={{
            padding: "10px 20px",
            marginRight: "10px",
            backgroundColor: "#4CAF50",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: capturing ? "not-allowed" : "pointer"
          }}
        >
          {capturing ? "Capturing..." : "Capture from Stream"}
        </button>

        <label style={{ marginLeft: "10px" }}>
          Or upload file:
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png"
            style={{ marginLeft: "10px" }}
          />
        </label>
        
        <button
          onClick={handleFileUpload}
          disabled={capturing}
          style={{
            padding: "10px 20px",
            marginLeft: "10px",
            backgroundColor: "#2196F3",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: capturing ? "not-allowed" : "pointer"
          }}
        >
          {capturing ? "Uploading..." : "Upload File"}
        </button>
      </div>

      {lastResult && (
        <div style={{
          padding: "10px",
          backgroundColor: lastResult.saved ? "#E8F5E9" : "#FFEBEE",
          borderRadius: "4px",
          marginTop: "10px"
        }}>
          <p><strong>Last Result:</strong></p>
          <p>Status: {lastResult.saved ? "✓ Saved" : "✗ Failed"}</p>
          <p>Label: {lastResult.label}</p>
          {lastResult.path && <p>Path: {lastResult.path}</p>}
        </div>
      )}
    </div>
  );
};

// ============== EXAMPLE 4: Vue.js Component ==============

/**
 * Vue.js component for face capture
 */
const VueFaceCaptureComponent = {
  data() {
    return {
      label: "unknown",
      confidence: 0.95,
      capturing: false,
      lastResult: null
    };
  },
  methods: {
    async handleCapture() {
      this.capturing = true;
      try {
        const result = await captureFromVideoStream("streamVideo", this.label, this.confidence);
        this.lastResult = result;
        if (result?.saved) {
          alert(`Face saved successfully!\nPath: ${result.path}`);
        }
      } finally {
        this.capturing = false;
      }
    },
    async handleFileUpload() {
      this.capturing = true;
      try {
        const result = await uploadFaceImage(this.$refs.fileInput, this.label, this.confidence);
        this.lastResult = result;
        if (result?.saved) {
          alert(`Face uploaded successfully!\nPath: ${result.path}`);
        }
      } finally {
        this.capturing = false;
      }
    }
  },
  template: `
    <div style="padding: 20px; border: 1px solid #ccc;">
      <h2>Face Capture (Vue)</h2>
      
      <input 
        v-model="label" 
        placeholder="Person name"
        style="margin-bottom: 10px; padding: 5px;"
      />
      
      <input 
        v-model.number="confidence" 
        type="number" 
        min="0" 
        max="1" 
        step="0.01"
        style="margin-bottom: 10px; margin-left: 10px; padding: 5px;"
      />
      
      <button 
        @click="handleCapture" 
        :disabled="capturing"
        style="margin: 10px; padding: 10px 20px; background-color: #4CAF50; color: white;"
      >
        {{ capturing ? 'Capturing...' : 'Capture' }}
      </button>
      
      <input 
        ref="fileInput"
        type="file" 
        accept="image/jpeg,image/png"
        style="margin: 10px;"
      />
      
      <button 
        @click="handleFileUpload" 
        :disabled="capturing"
        style="margin: 10px; padding: 10px 20px; background-color: #2196F3; color: white;"
      >
        {{ capturing ? 'Uploading...' : 'Upload' }}
      </button>
      
      <div v-if="lastResult" style="margin-top: 15px; padding: 10px; background-color: #f0f0f0;">
        <p><strong>Result:</strong> {{ lastResult.saved ? '✓ Saved' : '✗ Failed' }}</p>
        <p>Label: {{ lastResult.label }}</p>
        <p v-if="lastResult.path">Path: {{ lastResult.path }}</p>
      </div>
    </div>
  `
};

// ============== EXAMPLE 5: Vanilla JavaScript with Button ==============

/**
 * Setup capture buttons on page load
 */
document.addEventListener("DOMContentLoaded", function() {
  // Setup capture button
  const captureBtn = document.getElementById("captureBtn");
  if (captureBtn) {
    captureBtn.addEventListener("click", async () => {
      const label = document.getElementById("labelInput")?.value || "unknown";
      const confidence = parseFloat(document.getElementById("confidenceInput")?.value || 0.95);
      await captureFromVideoStream("streamVideo", label, confidence);
    });
  }

  // Setup upload button
  const uploadBtn = document.getElementById("uploadBtn");
  if (uploadBtn) {
    uploadBtn.addEventListener("click", async () => {
      const label = document.getElementById("labelInput")?.value || "unknown";
      const confidence = parseFloat(document.getElementById("confidenceInput")?.value || 0.95);
      const fileInput = document.getElementById("faceFile");
      await uploadFaceImage(fileInput, label, confidence);
    });
  }
});

// ============== HELPER: Check Backend Health ==============

/**
 * Verify backend is running and endpoints are available
 */
async function checkBackendHealth() {
  try {
    const response = await fetch("http://192.168.1.209:8000/");
    if (!response.ok) throw new Error("Backend not responding");
    
    const data = await response.json();
    console.log("✓ Backend is healthy:", data);
    console.log("✓ Capture endpoints available:");
    console.log("  - POST /capture_face_upload");
    console.log("  - POST /capture_face_b64");
    return true;
  } catch (error) {
    console.error("✗ Backend health check failed:", error);
    alert("Backend is not available. Make sure the FastAPI server is running on http://192.168.1.209:8000");
    return false;
  }
}

// ============== EXPORT ==============

// Uncomment if using as module
// export { captureFromVideoStream, uploadFaceImage, checkBackendHealth };