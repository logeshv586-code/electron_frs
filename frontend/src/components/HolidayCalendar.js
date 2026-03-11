import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, Plus, Edit2, Trash2, X } from 'lucide-react';
import { format, addMonths, subMonths, startOfMonth, startOfWeek, endOfMonth, endOfWeek, isSameMonth, isSameDay, addDays } from 'date-fns';
import './HolidayCalendar.css';

const HolidayCalendar = () => {
    const [currentDate, setCurrentDate] = useState(new Date());
    const [showAddModal, setShowAddModal] = useState(false);
    const [editIndex, setEditIndex] = useState(null);
    const [newHoliday, setNewHoliday] = useState({ date: '', name: '', type: 'Public Holiday' });
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());

    const initialHolidays = [
        { date: new Date(new Date().getFullYear(), 0, 1), name: "New Year's Day", type: "Public Holiday" },
        { date: new Date(new Date().getFullYear(), 0, 14), name: "Pongal", type: "Public Holiday" },
        { date: new Date(new Date().getFullYear(), 0, 26), name: "Republic Day", type: "National Holiday" },
        { date: new Date(new Date().getFullYear(), 3, 14), name: "Dr Ambedkar Jayanti", type: "National Holiday" },
        { date: new Date(new Date().getFullYear(), 4, 1), name: "Labor Day", type: "Public Holiday" },
        { date: new Date(new Date().getFullYear(), 7, 15), name: "Independence Day", type: "National Holiday" },
        { date: new Date(new Date().getFullYear(), 9, 2), name: "Gandhi Jayanti", type: "National Holiday" },
        { date: new Date(new Date().getFullYear(), 10, 1), name: "Diwali", type: "Public Holiday" },
        { date: new Date(new Date().getFullYear(), 11, 25), name: "Christmas Day", type: "Public Holiday" },
    ];

    const [holidays, setHolidays] = useState(initialHolidays);

    const nextMonth = () => setCurrentDate(addMonths(currentDate, 1));
    const prevMonth = () => setCurrentDate(subMonths(currentDate, 1));
    const today = () => setCurrentDate(new Date());

    const handleYearChange = (e) => {
        const year = parseInt(e.target.value);
        setSelectedYear(year);
        setCurrentDate(new Date(year, currentDate.getMonth(), 1));
    };

    const renderHeader = () => {
        const years = [];
        for (let y = 2024; y <= 2030; y++) years.push(y);

        return (
            <div className="calendar-header">
                <div className="calendar-nav">
                    <button onClick={today} className="btn-today">Today</button>
                    <button onClick={prevMonth} className="btn-nav"><ChevronLeft size={20} /></button>
                    <button onClick={nextMonth} className="btn-nav"><ChevronRight size={20} /></button>
                    <h2 className="current-month">{format(currentDate, 'MMMM yyyy')}</h2>
                    <select value={selectedYear} onChange={handleYearChange} className="select-clean" style={{ width: 'auto', marginLeft: '8px', padding: '4px 8px' }}>
                        {years.map(y => <option key={y} value={y}>{y}</option>)}
                    </select>
                </div>
                <button className="btn-add-holiday" onClick={() => { setEditIndex(null); setNewHoliday({ date: '', name: '', type: 'Public Holiday' }); setShowAddModal(true); }}>
                    <Plus size={16} /> Add Holiday
                </button>
            </div>
        );
    };

    const renderDays = () => {
        const dateFormat = "EEEE";
        const days = [];
        let startDate = startOfWeek(currentDate);

        for (let i = 0; i < 7; i++) {
            days.push(
                <div className="day-name col-center" key={i}>
                    {format(addDays(startDate, i), dateFormat)}
                </div>
            );
        }
        return <div className="days-row">{days}</div>;
    };

    const renderCells = () => {
        const monthStart = startOfMonth(currentDate);
        const monthEnd = endOfMonth(monthStart);
        const startDate = startOfWeek(monthStart);
        const endDate = endOfWeek(monthEnd);

        const dateFormat = "d";
        const rows = [];
        let days = [];
        let day = startDate;
        let formattedDate = "";

        while (day <= endDate) {
            for (let i = 0; i < 7; i++) {
                formattedDate = format(day, dateFormat);
                const cloneDay = day;
                const matchingHolidays = holidays.filter(h => isSameDay(h.date, cloneDay));

                days.push(
                    <div
                        className={`cell ${!isSameMonth(day, monthStart)
                            ? "disabled"
                            : isSameDay(day, new Date())
                                ? "selected"
                                : ""
                            }`}
                        key={day}
                    >
                        <span className="number">{formattedDate}</span>
                        <div className="events-container">
                            {matchingHolidays.map((holiday, idx) => (
                                <div key={idx} className={`event-badge ${holiday.type === 'Public Holiday' ? 'public' : holiday.type === 'Company Holiday' ? 'company' : 'national'}`}>
                                    {holiday.name}
                                </div>
                            ))}
                        </div>
                    </div>
                );
                day = addDays(day, 1);
            }
            rows.push(
                <div className="dates-row" key={day}>
                    {days}
                </div>
            );
            days = [];
        }
        return <div className="calendar-body">{rows}</div>;
    };

    const handleAddHoliday = (e) => {
        e.preventDefault();
        if (newHoliday.name && newHoliday.date) {
            const parsedDate = new Date(newHoliday.date);
            const adjustedDate = new Date(parsedDate.getTime() + Math.abs(parsedDate.getTimezoneOffset() * 60000));

            if (editIndex !== null) {
                const updated = [...holidays];
                updated[editIndex] = { ...newHoliday, date: adjustedDate };
                setHolidays(updated);
            } else {
                setHolidays([...holidays, { ...newHoliday, date: adjustedDate }]);
            }
            setShowAddModal(false);
            setNewHoliday({ date: '', name: '', type: 'Public Holiday' });
            setEditIndex(null);
        }
    };

    const handleEdit = (idx) => {
        const h = holidays[idx];
        setEditIndex(idx);
        setNewHoliday({
            name: h.name,
            date: format(h.date, 'yyyy-MM-dd'),
            type: h.type
        });
        setShowAddModal(true);
    };

    const handleDelete = (idx) => {
        if (window.confirm(`Delete holiday "${holidays[idx].name}"?`)) {
            setHolidays(holidays.filter((_, i) => i !== idx));
        }
    };

    const typeColors = {
        'Public Holiday': '#3b82f6',
        'National Holiday': '#f59e0b',
        'Company Holiday': '#10b981'
    };

    return (
        <div className="holiday-calendar-container">
            <div className="calendar-card">
                {renderHeader()}
                <div className="calendar-grid">
                    {renderDays()}
                    {renderCells()}
                </div>
            </div>

            <div className="holiday-list-card">
                <h3>All Holidays ({holidays.length})</h3>
                <div className="holiday-list">
                    {holidays
                        .sort((a, b) => a.date - b.date)
                        .map((holiday, idx) => (
                            <div key={idx} className="holiday-list-item">
                                <div className="holiday-date">
                                    <span className="month">{format(holiday.date, 'MMM')}</span>
                                    <span className="day">{format(holiday.date, 'dd')}</span>
                                </div>
                                <div className="holiday-details">
                                    <h4>{holiday.name}</h4>
                                    <span className="holiday-type">{holiday.type}</span>
                                </div>
                                <div className="holiday-actions" style={{ marginLeft: 'auto', display: 'flex', gap: '4px' }}>
                                    <button onClick={() => handleEdit(idx)} className="btn-icon" title="Edit" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: 'var(--text-secondary)' }}>
                                        <Edit2 size={14} />
                                    </button>
                                    <button onClick={() => handleDelete(idx)} className="btn-icon" title="Delete" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: '#ef4444' }}>
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                        ))}
                </div>

                {/* Color Legend */}
                <div style={{ marginTop: '16px', padding: '12px', borderTop: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Holiday Types</div>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                        {Object.entries(typeColors).map(([type, color]) => (
                            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem' }}>
                                <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: color }}></div>
                                <span style={{ color: 'var(--text-secondary)' }}>{type}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {showAddModal && (
                <div className="modal-overlay">
                    <div className="modal-content">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                            <h3 style={{ margin: 0 }}>{editIndex !== null ? 'Edit Holiday' : 'Add New Holiday'}</h3>
                            <button onClick={() => setShowAddModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                                <X size={20} />
                            </button>
                        </div>
                        <form onSubmit={handleAddHoliday}>
                            <div className="form-group">
                                <label>Holiday Name</label>
                                <input
                                    type="text"
                                    required
                                    value={newHoliday.name}
                                    onChange={e => setNewHoliday({ ...newHoliday, name: e.target.value })}
                                    className="input-clean"
                                />
                            </div>
                            <div className="form-group">
                                <label>Date</label>
                                <input
                                    type="date"
                                    required
                                    value={newHoliday.date}
                                    onChange={e => setNewHoliday({ ...newHoliday, date: e.target.value })}
                                    className="input-clean"
                                />
                            </div>
                            <div className="form-group">
                                <label>Type</label>
                                <select
                                    value={newHoliday.type}
                                    onChange={e => setNewHoliday({ ...newHoliday, type: e.target.value })}
                                    className="select-clean"
                                >
                                    <option>Public Holiday</option>
                                    <option>National Holiday</option>
                                    <option>Company Holiday</option>
                                </select>
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn-cancel" onClick={() => setShowAddModal(false)}>Cancel</button>
                                <button type="submit" className="btn-save">{editIndex !== null ? 'Update' : 'Save'} Holiday</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default HolidayCalendar;
