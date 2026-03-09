#!/usr/bin/env python3
"""
Unified Face Recognition System Server
Starts all backend services on a single port (8000)
"""

import uvicorn
import logging
import sys
import os

# Add the backend_face directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Start the unified Face Recognition System API server"""
    try:
        logger.info("=" * 60)
        logger.info("Starting Face Recognition System - Unified Backend")
        logger.info("=" * 60)
        logger.info("Port: 8005")
        logger.info("Host: 0.0.0.0")
        logger.info("Services included:")
        logger.info("  - Camera Management & Face Recognition")
        logger.info("  - Event Management")
        logger.info("  - Person Registration")
        logger.info("  - Face Matching")
        logger.info("  - Video Processing")
        logger.info("=" * 60)
        
        # Import and run the main app
        from main import app
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8005,
            log_level="info",
            access_log=True,
            reload=False  # Set to True for development
        )
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
