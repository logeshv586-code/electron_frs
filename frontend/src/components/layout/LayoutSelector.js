import React from 'react';
import './LayoutSelector.css';

const LayoutSelector = ({ currentLayout, onLayoutChange, disabled = false }) => {
  const layouts = [
    { id: '1x1', name: '1×1', icon: '⬜' },
    { id: '2x2', name: '2×2', icon: '⬜⬜\n⬜⬜' },
    { id: '3x3', name: '3×3', icon: '⬜⬜⬜\n⬜⬜⬜\n⬜⬜⬜' },
    { id: '4x4', name: '4×4', icon: '⬜⬜⬜⬜\n⬜⬜⬜⬜\n⬜⬜⬜⬜\n⬜⬜⬜⬜' },
    { id: '2x3', name: '2×3', icon: '⬜⬜\n⬜⬜\n⬜⬜' },
    { id: '3x2', name: '3×2', icon: '⬜⬜⬜\n⬜⬜⬜' }
  ];

  return (
    <div className="layout-selector">
      <label className="layout-label">Grid Layout:</label>
      <div className="layout-options">
        {layouts.map(layout => (
          <button
            key={layout.id}
            className={`layout-option ${currentLayout === layout.id ? 'active' : ''}`}
            onClick={() => onLayoutChange(layout.id)}
            disabled={disabled}
            title={`${layout.name} Grid`}
          >
            <div className="layout-preview">
              <div className={`grid-preview grid-${layout.id}`}>
                {Array.from({ length: parseInt(layout.id.split('x')[0]) * parseInt(layout.id.split('x')[1]) }).map((_, i) => (
                  <div key={i} className="grid-cell"></div>
                ))}
              </div>
            </div>
            <span className="layout-name">{layout.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default LayoutSelector;
