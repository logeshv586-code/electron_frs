import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, Calendar, Clock, FileSpreadsheet, FileText, Filter, Search, Users, UserX } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import AuthenticatedImage from '../common/AuthenticatedImage';
import { API_BASE_URL } from '../../utils/apiConfig';
import './AttendanceReport.css';

const localDate = () => {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
};

const AttendanceReport = ({ reportType, setActiveTab }) => {
  const token = useAuthStore((state) => state.token);
  const [reportData, setReportData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [targetDate, setTargetDate] = useState(localDate());
  const [startDate, setStartDate] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() - 7);
    return date.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(localDate());
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
      const date = new Date();
      date.setDate(date.getDate() - 7);
      setStartDate(date.toISOString().slice(0, 10));
      setEndDate(localDate());
    }
    if (reportType === 'month-report') {
      const date = new Date();
      date.setDate(1);
      setStartDate(date.toISOString().slice(0, 10));
      setEndDate(localDate());
    }
  }, [reportType]);

  useEffect(() => {
    let cancelled = false;
    const fetchAttendanceData = async () => {
      setLoading(true);
      setError('');
      const endpoint = isAggregate
        ? `${API_BASE_URL}/api/events/attendance/aggregate?start_date=${startDate}&end_date=${endDate}`
        : `${API_BASE_URL}/api/events/attendance?target_date=${targetDate}`;
      try {
        const response = await fetch(endpoint, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'Could not load attendance data.');
        if (!cancelled) setReportData(payload.attendance || payload.aggregate || []);
      } catch (requestError) {
        if (!cancelled) setError(requestError.message || 'Could not load attendance data.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchAttendanceData();
    return () => { cancelled = true; };
  }, [targetDate, startDate, endDate, reportType, isAggregate, token]);

  const title = useMemo(() => {
    if (reportType === 'day-report') return 'Daily Attendance';
    if (reportType === 'week-report') return 'Weekly Attendance';
    if (reportType === 'month-report') return 'Monthly Attendance';
    return 'Attendance Report';
  }, [reportType]);

  const filteredData = useMemo(() => reportData.filter((record) => {
    const query = searchTerm.trim().toLowerCase();
    const matchesSearch = !query
      || String(record.name || '').toLowerCase().includes(query)
      || String(record.emp_id || '').toLowerCase().includes(query)
      || String(record.department || '').toLowerCase().includes(query);
    if (!matchesSearch || statusFilter === 'All') return matchesSearch;
    if (isAggregate) {
      if (statusFilter === 'Present') return Number(record.total_present || 0) > 0;
      if (statusFilter === 'Absent') return Number(record.total_present || 0) === 0;
      if (statusFilter === 'Late') return Number(record.total_late || 0) > 0;
      return true;
    }
    if (statusFilter === 'Present') return record.status === 'Present' && !record.is_late;
    if (statusFilter === 'Absent') return record.status === 'Absent';
    if (statusFilter === 'Late') return !!record.is_late || record.status === 'Late';
    return true;
  }), [reportData, searchTerm, statusFilter, isAggregate]);

  const metrics = useMemo(() => ({
    present: isAggregate ? reportData.reduce((sum, record) => sum + Number(record.total_present || 0), 0) : reportData.filter((record) => ['Present', 'Late'].includes(record.status)).length,
    absent: isAggregate ? reportData.reduce((sum, record) => sum + Number(record.total_absent || 0), 0) : reportData.filter((record) => record.status === 'Absent').length,
    late: isAggregate ? reportData.reduce((sum, record) => sum + Number(record.total_late || 0), 0) : reportData.filter((record) => record.is_late || record.status === 'Late').length,
    total: reportData.length,
  }), [reportData, isAggregate]);

  const exportToCSV = () => {
    if (!filteredData.length) return;
    const headers = isAggregate
      ? ['S.No', 'EMP ID', 'Name', 'Department', 'Designation', 'Email', 'Total Present', 'Total Absent', 'Total Late', 'Total Hrs', 'Avg Hrs/Day']
      : ['S.No', 'EMP ID', 'Name', 'Department', 'Designation', 'Email', 'Status', 'Punch In', 'Punch Out', 'Working Hours', 'Late'];
    const escape = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
    const rows = filteredData.map((row, index) => {
      const common = [row.s_no || index + 1, row.emp_id, row.name, row.department, row.designation, row.email];
      const tail = isAggregate
        ? [row.total_present, row.total_absent, row.total_late, row.total_working_hours, row.avg_working_hours]
        : [row.status, row.punch_in, row.punch_out, row.working_hours, row.is_late ? 'Yes' : 'No'];
      return [...common, ...tail].map(escape).join(',');
    });
    const blob = new Blob([[headers.join(','), ...rows].join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${title.replace(/\s+/g, '_')}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const exportToPDF = async () => {
    setError('');
    const endpoint = isAggregate
      ? `${API_BASE_URL}/api/events/export/attendance-aggregate-pdf?start_date=${startDate}&end_date=${endDate}`
      : `${API_BASE_URL}/api/events/export/attendance-pdf?target_date=${targetDate}`;
    try {
      const response = await fetch(endpoint, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Could not generate the PDF report.');
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = isAggregate ? `attendance_${startDate}_to_${endDate}.pdf` : `attendance_${targetDate}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setError(exportError.message || 'Could not export the PDF.');
    }
  };

  return (
    <div className="attendance-report-container product-surface-page">
      <div className="report-header product-page-header">
        <div className="report-title-area">
          {setActiveTab && <button className="btn-back-clean" onClick={() => setActiveTab('dashboard')}><ArrowLeft size={15} /> Back</button>}
          <div><h2>{title}</h2><p>Database-backed first-in / last-out attendance records.</p></div>
        </div>

        <div className="report-actions compact-toolbar">
          <div className="search-bar"><Search size={15} /><input placeholder="Employee ID, name or department" value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} /></div>
          <label className="status-filter"><Filter size={14} /><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>All</option><option>Present</option><option>Absent</option><option>Late</option></select></label>
          {isAggregate ? (
            <div className="date-range-control"><Calendar size={14} /><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /><span>to</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></div>
          ) : (
            <label className="date-picker-wrap"><Calendar size={14} /><input type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} /></label>
          )}
          <button className="btn-export" onClick={exportToCSV}><FileSpreadsheet size={14} /> CSV</button>
          <button className="btn-export" onClick={exportToPDF}><FileText size={14} /> PDF</button>
        </div>
      </div>

      <div className="summary-bar compact-summary-bar">
        <div className="summary-card present"><Users size={16} /><span><strong>{metrics.present}</strong> Present</span></div>
        <div className="summary-card absent"><UserX size={16} /><span><strong>{metrics.absent}</strong> Absent</span></div>
        <div className="summary-card late"><AlertTriangle size={16} /><span><strong>{metrics.late}</strong> Late</span></div>
        <div className="summary-card total"><Clock size={16} /><span><strong>{metrics.total}</strong> Employees</span></div>
      </div>

      {error && <div className="error-message attendance-error">{error}</div>}

      <div className="table-container attendance-table-shell">
        {loading ? (
          <div className="loading-state"><div className="spinner" /><p>Loading attendance...</p></div>
        ) : (
          <table className="attendance-table">
            <thead>
              <tr>
                <th>#</th><th>EMP ID</th><th>Employee</th><th>Department</th><th>Designation</th><th>Email</th>
                {isAggregate ? <><th>Present</th><th>Absent</th><th>Late</th><th>Total Hrs</th><th>Avg / Day</th></> : <><th>Status</th><th>First In</th><th>Last Out</th><th>Working Hrs</th><th>Arrival</th></>}
              </tr>
            </thead>
            <tbody>
              {filteredData.length ? filteredData.map((record, index) => (
                <tr key={`${record.emp_id || record.name || 'employee'}-${index}`}>
                  <td>{record.s_no || index + 1}</td>
                  <td className="emp-id">{record.emp_id || '-'}</td>
                  <td><div className="name-cell">
                    <span className="mini-avatar-wrap">
                      {record.photo_path && <AuthenticatedImage src={record.photo_path} alt={record.name || 'Employee'} className="mini-avatar" />}
                      <span className="mini-avatar-placeholder">{String(record.name || record.email || 'U').charAt(0).toUpperCase()}</span>
                    </span>
                    <span>{record.name || '-'}</span>
                  </div></td>
                  <td>{record.department || '-'}</td><td>{record.designation || '-'}</td><td className="muted-cell">{record.email || '-'}</td>
                  {isAggregate ? (
                    <><td className="metric-positive">{record.total_present || 0}</td><td className="metric-negative">{record.total_absent || 0}</td><td className="metric-warning">{record.total_late || 0}</td><td>{record.total_working_hours || '-'}</td><td>{record.avg_working_hours || '-'}</td></>
                  ) : (
                    <><td><span className={`status-badge ${String(record.status || 'absent').toLowerCase().replace(/\s+/g, '-')}`}>{record.status || 'Absent'}</span></td><td className="time-cell">{record.punch_in || '-'}</td><td className="time-cell">{record.punch_out || '-'}</td><td className="time-cell">{record.working_hours || '-'}</td><td>{record.is_late || record.status === 'Late' ? <span className="status-badge late">Late</span> : record.status === 'Present' ? <span className="status-badge on-time">On time</span> : '-'}</td></>
                  )}
                </tr>
              )) : <tr><td colSpan={11} className="no-data">No attendance records match this selection.</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default AttendanceReport;
