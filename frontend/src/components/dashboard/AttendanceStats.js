import React, { useState, useEffect } from 'react';
import { Users, UserX, Clock, Calendar, Briefcase, Home, AlertTriangle } from 'lucide-react';
import { API_BASE_URL } from '../../utils/apiConfig';
import './AttendanceStats.css';

const AttendanceStats = ({ setActiveTab }) => {
    const [stats, setStats] = useState({
        total_users: 0,
        present: 0,
        not_marked: 0,
        late: 0,
        half_day: 0,
        on_duty: 0,
        leave: 0,
        weekoff: 0,
        wfh: 0
    });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetchStats();
    }, []);

    const fetchStats = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE_URL}/api/events/dashboard-stats`);
            if (res.ok) {
                const data = await res.json();
                setStats(data);
            }
        } catch (error) {
            console.error("Error fetching attendance stats:", error);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return <div className="attendance-stats-loading">Loading stats...</div>;
    }

    const handleCardClick = (label) => {
        if (!setActiveTab) return;
        let filterStatus = '';
        if (label === 'Present') filterStatus = 'Present';
        if (label === 'Not Marked') filterStatus = 'Absent';
        if (label === 'Late') filterStatus = 'Late';

        if (filterStatus) {
            localStorage.setItem('attendanceFilter', filterStatus);
            setActiveTab('attendance-report');
        }
    };

    const statCards = [
        { label: 'Present', value: stats.present, color: '#10b981', icon: <Users size={20} /> },
        { label: 'Not Marked', value: stats.not_marked, color: '#ef4444', icon: <UserX size={20} /> },
        { label: 'Late', value: stats.late, color: '#f97316', icon: <AlertTriangle size={20} /> },
        { label: 'Half Day', value: stats.half_day, color: '#f59e0b', icon: <Clock size={20} /> },
        { label: 'On-Duty', value: stats.on_duty, color: '#3b82f6', icon: <Briefcase size={20} /> },
        { label: 'Leave', value: stats.leave, color: '#8b5cf6', icon: <Calendar size={20} /> },
        { label: 'Weekoff', value: stats.weekoff, color: '#64748b', icon: <Calendar size={20} /> },
        { label: 'Work from Home', value: stats.wfh, color: '#0ea5e9', icon: <Home size={20} /> },
        { label: 'Total Users', value: stats.total_users, color: '#0f172a', icon: <Users size={20} /> }
    ];

    return (
        <div className="attendance-stats-grid">
            {statCards.map((stat, idx) => {
                const isClickable = ['Present', 'Not Marked', 'Late'].includes(stat.label);
                return (
                    <div
                        className="stat-card"
                        key={idx}
                        style={{ '--stat-color': stat.color, cursor: isClickable ? 'pointer' : 'default' }}
                        onClick={() => handleCardClick(stat.label)}
                    >
                        <div className="stat-icon-wrapper" style={{ color: stat.color, backgroundColor: `${stat.color}15` }}>
                            {stat.icon}
                        </div>
                        <div className="stat-info">
                            <span className="stat-value">{stat.value}</span>
                            <span className="stat-label">{stat.label}</span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

export default AttendanceStats;
