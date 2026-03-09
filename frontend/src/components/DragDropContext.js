import React, { createContext, useContext, useState, useCallback } from 'react';

const DragDropContext = createContext();

export const useDragDrop = () => {
  const context = useContext(DragDropContext);
  if (!context) {
    throw new Error('useDragDrop must be used within a DragDropProvider');
  }
  return context;
};

export const DragDropProvider = ({ children }) => {
  const [draggedItem, setDraggedItem] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const startDrag = useCallback((item, sourceType = 'default') => {
    setDraggedItem({ ...item, sourceType });
    setIsDragging(true);
  }, []);

  const endDrag = useCallback(() => {
    setDraggedItem(null);
    setDropTarget(null);
    setIsDragging(false);
  }, []);

  const setDropTargetHandler = useCallback((target) => {
    setDropTarget(target);
  }, []);

  const handleDrop = useCallback((targetInfo, onDrop) => {
    if (draggedItem && onDrop) {
      onDrop(draggedItem, targetInfo);
    }
    endDrag();
  }, [draggedItem, endDrag]);

  const value = {
    draggedItem,
    dropTarget,
    isDragging,
    startDrag,
    endDrag,
    setDropTarget: setDropTargetHandler,
    handleDrop
  };

  return (
    <DragDropContext.Provider value={value}>
      {children}
    </DragDropContext.Provider>
  );
};

// Draggable component
export const Draggable = ({ 
  children, 
  item, 
  sourceType = 'default',
  onDragStart,
  onDragEnd,
  disabled = false 
}) => {
  const { startDrag, endDrag } = useDragDrop();

  const handleDragStart = (e) => {
    if (disabled) return;
    
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', ''); // For Firefox compatibility
    
    startDrag(item, sourceType);
    
    if (onDragStart) {
      onDragStart(item, e);
    }
  };

  const handleDragEnd = (e) => {
    if (disabled) return;
    
    endDrag();
    
    if (onDragEnd) {
      onDragEnd(item, e);
    }
  };

  return (
    <div
      draggable={!disabled}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      style={{
        cursor: disabled ? 'default' : 'grab',
        opacity: disabled ? 0.5 : 1
      }}
    >
      {children}
    </div>
  );
};

// Droppable component
export const Droppable = ({ 
  children, 
  targetInfo, 
  onDrop, 
  onDragOver,
  onDragEnter,
  onDragLeave,
  acceptTypes = ['default'],
  disabled = false 
}) => {
  const { draggedItem, setDropTarget, handleDrop } = useDragDrop();
  const [isOver, setIsOver] = useState(false);

  const canAcceptDrop = (item) => {
    if (!item || disabled) return false;
    return acceptTypes.includes(item.sourceType) || acceptTypes.includes('*');
  };

  const handleDragOver = (e) => {
    if (!canAcceptDrop(draggedItem)) return;
    
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    
    if (onDragOver) {
      onDragOver(e, draggedItem);
    }
  };

  const handleDragEnter = (e) => {
    if (!canAcceptDrop(draggedItem)) return;
    
    e.preventDefault();
    setIsOver(true);
    setDropTarget(targetInfo);
    
    if (onDragEnter) {
      onDragEnter(e, draggedItem);
    }
  };

  const handleDragLeave = (e) => {
    if (!canAcceptDrop(draggedItem)) return;
    
    // Only trigger leave if we're actually leaving the droppable area
    if (!e.currentTarget.contains(e.relatedTarget)) {
      setIsOver(false);
      setDropTarget(null);
      
      if (onDragLeave) {
        onDragLeave(e, draggedItem);
      }
    }
  };

  const handleDropEvent = (e) => {
    if (!canAcceptDrop(draggedItem)) return;
    
    e.preventDefault();
    setIsOver(false);
    
    handleDrop(targetInfo, onDrop);
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDropEvent}
      style={{
        position: 'relative',
        ...(isOver && canAcceptDrop(draggedItem) ? {
          backgroundColor: 'rgba(49, 130, 206, 0.1)',
          border: '2px dashed #3182ce'
        } : {})
      }}
    >
      {children}
    </div>
  );
};

export default DragDropProvider;
