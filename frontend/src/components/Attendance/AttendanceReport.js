import React, { useState, useEffect } from 'react';
import { Download, Search, Filter, Calendar, FileText, FileSpreadsheet, Users, UserX, AlertTriangle, Clock, ArrowLeft } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL, getApiUrl } from '../../utils/apiConfig';
import './AttendanceReport.css';

const AttendanceReport = ({ reportType, setActiveTab }) => {
    const { user: currentUser, token } = useAuthStore();
    const [reportData, setReportData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [targetDate, setTargetDate] = useState(new Date().toISOString().split('T')[0]);

    // For aggregate reports
    const [startDate, setStartDate] = useState(() => {
        const d = new Date();
        d.setDate(d.getDate() - 7);
        return d.toISOString().split('T')[0];
    });
    const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);

    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState('All');

    const isAggregate = reportType === 'week-report' || reportType === 'month-report';

    useEffect(() => {
        const initialFilter = localStorage.getItem('attendanceFilter');
        if (initialFilter) {
            setStatusFilter(initialFilter);
            localStorage.removeItem('attendanceFilter');
        }
    }, [reportType]);

    useEffect(() => {
        if (reportType === 'week-report') {
            const d = new Date();
            d.setDate(d.getDate() - 7);
            setStartDate(d.toISOString().split('T')[0]);
            setEndDate(new Date().toISOString().split('T')[0]);
        } else if (reportType === 'month-report') {
            const d = new Date();
            d.setDate(1);
            setStartDate(d.toISOString().split('T')[0]);
            setEndDate(new Date().toISOString().split('T')[0]);
        }
    }, [reportType]);

    useEffect(() => {
        fetchAttendanceData();
    }, [targetDate, startDate, endDate, reportType]);

    const fetchAttendanceData = async () => {
        try {
            setLoading(true);
            setError(null);

            const url = isAggregate
                ? `${API_BASE_URL}/api/events/attendance/aggregate?start_date=${startDate}&end_date=${endDate}`
                : `${API_BASE_URL}/api/events/attendance?target_date=${targetDate}`;

            const response = await fetch(url, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch attendance data: ${response.statusText}`);
            }

            const data = await response.json();
            setReportData(data.attendance || data.aggregate || []);
        } catch (err) {
            console.error("Error fetching attendance:", err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const getDayTitle = () => {
        switch (reportType) {
            case 'day-report': return 'Daily Attendance Report';
            case 'week-report': return 'Weekly Attendance Report';
            case 'month-report': return 'Monthly Attendance Report';
            default: return 'Attendance Report';
        }
    };

    const filteredData = reportData.filter(record => {
        const matchesSearch = record.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            (record.emp_id && record.emp_id.toLowerCase().includes(searchTerm.toLowerCase()));

        let matchesStatus = true;
        if (!isAggregate) {
            if (statusFilter === 'Present') matchesStatus = record.status === 'Present' && !record.is_late;
            else if (statusFilter === 'Absent') matchesStatus = record.status === 'Absent';
            else if (statusFilter === 'Late') matchesStatus = record.is_late;
        } else {
            if (statusFilter === 'Present') matchesStatus = (record.total_present || 0) > 0;
            else if (statusFilter === 'Absent') matchesStatus = (record.total_present || 0) === 0;
            else if (statusFilter === 'Late') matchesStatus = (record.total_late || 0) > 0;
        }

        return matchesSearch && matchesStatus;
    });

    // Summary calculations
    const totalPresent = isAggregate ? reportData.reduce((acc, r) => acc + (r.total_present || 0), 0) : reportData.filter(r => r.status === 'Present').length;
    const totalAbsent = isAggregate ? reportData.reduce((acc, r) => acc + (r.total_absent || 0), 0) : reportData.filter(r => r.status === 'Absent').length;
    const totalLate = isAggregate ? reportData.reduce((acc, r) => acc + (r.total_late || 0), 0) : reportData.filter(r => r.is_late).length;

    const exportToCSV = () => {
        if (filteredData.length === 0) return;

        const headers = isAggregate
            ? ['S.No', 'EMP ID', 'Name', 'Department', 'Designation', 'Total Present', 'Total Absent', 'Total Late', 'Total Hrs', 'Avg Hrs/Day']
            : ['S.No', 'EMP ID', 'Name', 'Department', 'Designation', 'Status', 'Punch In', 'Punch Out', 'Working Hours', 'Late'];

        const csvRows = [headers.join(',')];

        filteredData.forEach(row => {
            const values = [
                row.s_no || '',
                row.emp_id || '',
                `"${row.name || ''}"`,
                `"${row.department || ''}"`,
                `"${row.designation || ''}"`
            ];

            if (isAggregate) {
                values.push(row.total_present || 0);
                values.push(row.total_absent || 0);
                values.push(row.total_late || 0);
                values.push(row.total_working_hours || '-');
                values.push(row.avg_working_hours || '-');
            } else {
                values.push(row.status || '');
                values.push(row.punch_in || '');
                values.push(row.punch_out || '');
                values.push(row.working_hours || '-');
                values.push(row.is_late ? 'Yes' : 'No');
            }

            csvRows.push(values.join(','));
        });

        const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.setAttribute('hidden', '');
        a.setAttribute('href', url);
        a.setAttribute('download', `${getDayTitle().replace(/\s+/g, '_')}.csv`);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    const exportToPDF = () => {
        window.print();
    };

    return (
        <div className="attendance-report-container animate-fade-in">
            <div className="report-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {setActiveTab && (
                        <button
                            onClick={() => setActiveTab('dashboard')}
                            className="btn-back-clean"
                            style={{ background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-secondary)' }}
                        >
                            <ArrowLeft size={20} /> Back
                        </button>
                    )}
                    <div>
                        <h2 style={{ margin: 0 }}>{getDayTitle()}</h2>
                        <p className="subtitle" style={{ margin: '4px 0 0' }}>View and manage employee attendance logs</p>
                    </div>
                </div>
                <div className="report-actions">
                    <div className="search-bar">
                        <Search size={18} />
                        <input
                            type="text"
                            placeholder="Search by Employee ID or Name"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>

                    <div className="status-filter" style={{ display: 'flex', alignItems: 'center', background: 'var(--bg-input)', padding: '0 12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                        <Filter size={18} style={{ color: 'var(--text-secondary)', marginRight: '8px' }} />
                        <select
                            value={statusFilter}
                            onChange={(e) => setStatusFilter(e.target.value)}
                            style={{ background: 'transparent', border: 'none', color: 'var(--text-primary)', padding: '8px 0', outline: 'none', cursor: 'pointer' }}
                        >
                            <option value="All">All Statuses</option>
                            <option value="Present">Present</option>
                            <option value="Absent">Absent</option>
                            <option value="Late">Late</option>
                        </select>
                    </div>

                    {isAggregate ? (
                        <div className="date-picker-wrap" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <Calendar size={18} />
                            <input
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="date-input"
                            />
                            <span style={{ color: 'var(--text-secondary)' }}>to</span>
                            <input
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className="date-input"
                            />
                        </div>
                    ) : (
                        <div className="date-picker-wrap">
                            <Calendar size={18} />
                            <input
                                type="date"
                                value={targetDate}
                                onChange={(e) => setTargetDate(e.target.value)}
                                className="date-input"
                            />
                        </div>
                    )}

                    <div className="export-buttons" style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn-export" onClick={exportToCSV} title="Export as Excel/CSV">
                            <FileSpreadsheet size={18} /> CSV
                        </button>
                        <button className="btn-export pdf-btn" onClick={exportToPDF} title="Export as PDF">
                            <FileText size={18} /> PDF
                        </button>
                    </div>
                </div>
            </div>

            {/* Summary Bar */}
            <div className="summary-bar" style={{ display: 'flex', gap: '16px', marginBottom: '20px', flexWrap: 'wrap' }}>
                <div className="summary-card" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', background: 'rgba(16,185,129,0.1)', borderRadius: '8px', color: '#10b981' }}>
                    <Users size={18} /> <strong>{totalPresent}</strong> Present
                </div>
                <div className="summary-card" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', background: 'rgba(239,68,68,0.1)', borderRadius: '8px', color: '#ef4444' }}>
                    <UserX size={18} /> <strong>{totalAbsent}</strong> Absent
                </div>
                <div className="summary-card" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', background: 'rgba(249,115,22,0.1)', borderRadius: '8px', color: '#f97316' }}>
                    <AlertTriangle size={18} /> <strong>{totalLate}</strong> Late
                </div>
                <div className="summary-card" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', background: 'rgba(59,130,246,0.1)', borderRadius: '8px', color: '#3b82f6' }}>
                    <Clock size={18} /> <strong>{isAggregate ? filteredData.length : reportData.length}</strong> Total
                </div>
            </div>

            {error && (
                <div className="error-message">
                    {error}
                </div>
            )}

            <div className="table-container">
                {loading ? (
                    <div className="loading-state">
                        <div className="spinner"></div>
                        <p>Loading attendance records...</p>
                    </div>
                ) : (
                    <table className="attendance-table">
                        <thead>
                            <tr>
                                <th>S.No</th>
                                <th>EMP ID</th>
                                <th>Name</th>
                                <th>Department</th>
                                <th>Designation</th>
                                {isAggregate ? (
                                    <>
                                        <th>Total Present</th>
                                        <th>Total Absent</th>
                                        <th>Total Late</th>
                                        <th>Total Hrs</th>
                                        <th>Avg Hrs/Day</th>
                                    </>
                                ) : (
                                    <>
                                        <th>Status</th>
                                        <th>Punch In</th>
                                        <th>Punch Out</th>
                                        <th>Working Hrs</th>
                                        <th>Late</th>
                                    </>
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {filteredData.length > 0 ? (
                                filteredData.map((record, index) => (
                                    <tr key={record.emp_id || index}>
                                        <td>{record.s_no}</td>
                                        <td className="emp-id">{record.emp_id || '-'}</td>
                                        <td>
                                            <div className="name-cell">
                                                {record.photo_path ? (
                                                    <img
                                                        src={getApiUrl(record.photo_path)}
                                                        alt={record.name}
                                                        className="mini-avatar"
                                                        onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                                                    />
                                                ) : null}
                                                <div
                                                    className="mini-avatar-placeholder"
                                                    style={{ display: record.photo_path ? 'none' : 'flex' }}
                                                >
                                                    {record.name.charAt(0).toUpperCase()}
                                                </div>
                                                <span>{record.name}</span>
                                            </div>
                                        </td>
                                        <td>{record.department || '-'}</td>
                                        <td>{record.designation || '-'}</td>
                                        {isAggregate ? (
                                            <>
                                                <td style={{ color: '#10b981', fontWeight: 'bold' }}>{record.total_present}</td>
                                                <td style={{ color: '#ef4444', fontWeight: 'bold' }}>{record.total_absent}</td>
                                                <td style={{ color: '#f97316', fontWeight: 'bold' }}>{record.total_late}</td>
                                                <td>{record.total_working_hours}</td>
                                                <td>{record.avg_working_hours}</td>
                                            </>
                                        ) : (
                                            <>
                                                <td>
                                                    <span className={`status-badge ${record.status.toLowerCase().replace(' ', '-')}`}>
                                                        {record.status}
                                                    </span>
                                                </td>
                                                <td className="time-cell">{record.punch_in || '-'}</td>
                                                <td className="time-cell">{record.punch_out || '-'}</td>
                                                <td className="time-cell">{record.working_hours || '-'}</td>
                                                <td>
                                                    {record.is_late ? (
                                                        <span className="status-badge late" style={{ backgroundColor: 'rgba(249,115,22,0.15)', color: '#f97316' }}>Late</span>
                                                    ) : record.status === 'Present' ? (
                                                        <span className="status-badge on-time" style={{ backgroundColor: 'rgba(16,185,129,0.15)', color: '#10b981' }}>On Time</span>
                                                    ) : '-'}
                                                </td>
                                            </>
                                        )}
                                    </tr>
                                ))
                            ) : (
                                <tr>
                                    <td colSpan={isAggregate ? "10" : "10"} className="no-data">
                                        No attendance records found for this {isAggregate ? 'date range' : 'date'}.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
};

export default AttendanceReport;
