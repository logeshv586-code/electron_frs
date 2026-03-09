import React, { useRef, useState, useEffect } from 'react';
import { useDrag, useDrop } from 'react-dnd';
import { motion, AnimatePresence } from 'framer-motion';
import { useCameras } from './CameraManager';
import { useCameraStore } from '../../store/cameraStore';
import bookmarkIcon from '../../icon/bookmark.svg';
import MJPEGStreamPlayer from './MJPEGStreamPlayer';
import './DraggableVideoCell.css';

const DraggableVideoCell = ({ camera, index, moveCamera, isHighlighted, showControls: showControlsProp = false }) => {
  const ref = useRef(null);
  const [showControls, setShowControls] = useState(false);
  const [cellKey, setCellKey] = useState(Date.now());

  // Get bookmark state and actions directly from the store
  const store = useCameraStore();
  const { bookmarkedCameras, toggleBookmark } = store || {};

  const isBookmarked = bookmarkedCameras && bookmarkedCameras.has ? bookmarkedCameras.has(camera.id) : false;

  // Force re-render when component mounts
  useEffect(() => {
    setCellKey(Date.now());
  }, []);

  const [{ isDragging }, drag] = useDrag({
    type: 'CAMERA',
    item: { index },
    collect: (monitor) => ({
      isDragging: monitor.isDragging(),
    }),
  });

  const [, drop] = useDrop({
    accept: 'CAMERA',
    hover: (item, monitor) => {
      if (!ref.current) {
        return;
      }
      const dragIndex = item.index;
      const hoverIndex = index;

      if (dragIndex === hoverIndex) {
        return;
      }

      moveCamera(dragIndex, hoverIndex);
      item.index = hoverIndex;
    },
  });

  drag(drop(ref));

  const handleToggleBookmark = (e) => {
    e.stopPropagation();
    try {
      if (toggleBookmark && typeof toggleBookmark === 'function') {
        toggleBookmark(camera.id);
      }
    } catch (error) {
      console.error('Error toggling bookmark:', error);
    }
  };

  return (
    <motion.div
      ref={ref}
      className={`video-cell ${isHighlighted ? 'highlighted' : ''} ${isBookmarked ? 'bookmarked' : ''}`}
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{
        opacity: isDragging ? 0.5 : 1,
        scale: isDragging ? 1.05 : 1,
        boxShadow: isDragging ? '0 5px 15px rgba(0,0,0,0.3)' : 'none'
      }}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={{
        type: "spring",
        stiffness: 300,
        damping: 30
      }}
      whileHover={{
        scale: 1.02,
        boxShadow: '0 5px 15px rgba(0,0,0,0.2)'
      }}
      onMouseEnter={() => showControlsProp && setShowControls(true)}
      onMouseLeave={() => showControlsProp && setShowControls(false)}
    >
      <div className="video-placeholder">
        <AnimatePresence>
          {camera.ip || camera.streamUrl ? (
            <MJPEGStreamPlayer
              key={`stream-${camera.id}`}
              camera={camera}
            />
          ) : (
            <motion.div
              className="placeholder-content"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="camera-icon">📹</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="camera-info">
        {camera.name}
        {showControlsProp && showControls && (
          <button
            className={`bookmark-button ${isBookmarked ? 'bookmarked' : ''}`}
            onClick={handleToggleBookmark}
            title={isBookmarked ? "Remove from bookmarks" : "Add to bookmarks"}
          >
            <img
              src={bookmarkIcon}
              alt="Bookmark"
              style={{ width: '16px', height: '16px' }}
            />
          </button>
        )}
      </div>
    </motion.div>
  );
};

export default DraggableVideoCell;