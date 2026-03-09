import React, { useState } from 'react';
import './CameraPlayerControls.css';

const CameraPlayerControls = ({ onModeChange, onTimeChange }) => {
  const [mode, setMode] = useState('live');
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  
  // Get today's date in YYYY-MM-DD format for the date picker max value
  const today = new Date().toISOString().split('T')[0];
  
  // Set default date to today if not already set
  if (!selectedDate) {
    setSelectedDate(today);
  }
  
  const handleModeChange = (newMode) => {
    setMode(newMode);
    
    if (newMode === 'live') {
      // For live mode, pass null as the timestamp
      onModeChange('live');
      onTimeChange(null);
    } else {
      // For recorded mode, keep the current selection
      onModeChange('recorded');
      if (selectedDate && selectedTime) {
        handleTimeSelection();
      }
    }
  };
  
  const handleDateChange = (e) => {
    setSelectedDate(e.target.value);
    if (mode === 'recorded' && e.target.value && selectedTime) {
      handleTimeSelection(e.target.value, selectedTime);
    }
  };
  
  const handleTimeChange = (e) => {
    setSelectedTime(e.target.value);
    if (mode === 'recorded' && selectedDate && e.target.value) {
      handleTimeSelection(selectedDate, e.target.value);
    }
  };
  
  const handleTimeSelection = (date = selectedDate, time = selectedTime) => {
    // Create a timestamp from the date and time
    const timestamp = `${date}T${time}`;
    onTimeChange(timestamp);
  };
  
  return (
    <div className="camera-player-controls">
      <div className="mode-selector">
        <button 
          className={`mode-button ${mode === 'live' ? 'active' : ''}`}
          onClick={() => handleModeChange('live')}
        >
          <span className="live-indicator"></span>
          Live
        </button>
        <button 
          className={`mode-button ${mode === 'recorded' ? 'active' : ''}`}
          onClick={() => handleModeChange('recorded')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          Recorded
        </button>
      </div>
      
      {mode === 'recorded' && (
        <div className="time-selector">
          <div className="date-picker">
            <label htmlFor="date-select">Date:</label>
            <input 
              type="date" 
              id="date-select"
              value={selectedDate}
              onChange={handleDateChange}
              max={today}
            />
          </div>
          <div className="time-picker">
            <label htmlFor="time-select">Time:</label>
            <input 
              type="time" 
              id="time-select"
              value={selectedTime}
              onChange={handleTimeChange}
            />
          </div>
          <button 
            className="go-button"
            onClick={() => handleTimeSelection()}
            disabled={!selectedDate || !selectedTime}
          >
            Go
          </button>
        </div>
      )}
    </div>
  );
};

export default CameraPlayerControls;
