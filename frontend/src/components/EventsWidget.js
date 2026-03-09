import React, { useState } from 'react';
import FaceEvents from './FaceEvents';
import FindOccurrence from './FindOccurrence';
import './EventsWidget.css';

const EventsWidget = () => {
  const [activeTab, setActiveTab] = useState('face-events');

  return (
    <div className="events-widget">
      <div className="events-header-clean">
        <div className="header-title">
          <h2>Events</h2>
          <p>Monitor face recognition events and search occurrences</p>
        </div>
        <div className="mode-selector-pill">
          <button
            className={`mode-pill ${activeTab === 'face-events' ? 'active' : ''}`}
            onClick={() => setActiveTab('face-events')}
          >
            Face Events
          </button>
          <button
            className={`mode-pill ${activeTab === 'find-occurrence' ? 'active' : ''}`}
            onClick={() => setActiveTab('find-occurrence')}
          >
            Find Occurrence
          </button>
        </div>
      </div>
      
      <div className="tab-content">
        {activeTab === 'face-events' && <FaceEvents />}
        {activeTab === 'find-occurrence' && <FindOccurrence />}
      </div>
    </div>
  );
};

export default EventsWidget;
