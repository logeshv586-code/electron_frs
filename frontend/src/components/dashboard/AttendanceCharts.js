import React, { useState, useEffect } from 'react';
import { Bar, Doughnut } from 'react-chartjs-2';
import { API_BASE_URL } from '../../utils/apiConfig';

const AttendanceCharts = () => {
    const [weeklyData, setWeeklyData] = useState(null);
    const [deptData, setDeptData] = useState(null);

    useEffect(() => {
        fetchWeeklyData();
        fetchDeptData();
    }, []);

    const fetchWeeklyData = async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/api/events/attendance/weekly`);
            if (res.ok) {
                const data = await res.json();
                setWeeklyData(data.weekly);
            }
        } catch (err) {
            console.error("Error fetching weekly data:", err);
        }
    };

    const fetchDeptData = async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/api/events/attendance/department-stats`);
            if (res.ok) {
                const data = await res.json();
                setDeptData(data.departments);
            }
        } catch (err) {
            console.error("Error fetching department data:", err);
        }
    };

    const getComputedColor = (varName, fallback) => {
        try {
            const val = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
            return val || fallback;
        } catch { return fallback; }
    };

    const weeklyChartData = weeklyData ? {
        labels: weeklyData.map(d => d.day),
        datasets: [
            {
                label: 'Present',
                data: weeklyData.map(d => d.present),
                backgroundColor: 'rgba(16, 185, 129, 0.7)',
                borderColor: '#10b981',
                borderWidth: 1,
                borderRadius: 6,
            },
            {
                label: 'Absent',
                data: weeklyData.map(d => d.absent),
                backgroundColor: 'rgba(239, 68, 68, 0.7)',
                borderColor: '#ef4444',
                borderWidth: 1,
                borderRadius: 6,
            },
            {
                label: 'Late',
                data: weeklyData.map(d => d.late),
                backgroundColor: 'rgba(249, 115, 22, 0.7)',
                borderColor: '#f97316',
                borderWidth: 1,
                borderRadius: 6,
            }
        ]
    } : null;

    const weeklyOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                position: 'top',
                labels: { color: getComputedColor('--text-secondary', '#94a3b8'), usePointStyle: true, pointStyle: 'circle' }
            },
            title: { display: false }
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { color: getComputedColor('--text-secondary', '#94a3b8') }
            },
            y: {
                grid: { color: 'rgba(148, 163, 184, 0.1)' },
                ticks: { color: getComputedColor('--text-secondary', '#94a3b8'), stepSize: 1 },
                beginAtZero: true
            }
        }
    };

    const deptColors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#0ea5e9', '#f97316', '#64748b'];
    const deptChartData = deptData ? {
        labels: Object.keys(deptData),
        datasets: [{
            data: Object.values(deptData).map(d => d.present),
            backgroundColor: deptColors.slice(0, Object.keys(deptData).length),
            borderWidth: 0,
            hoverOffset: 8
        }]
    } : null;

    const deptOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                position: 'bottom',
                labels: { color: getComputedColor('--text-secondary', '#94a3b8'), usePointStyle: true, pointStyle: 'circle', padding: 16 }
            }
        },
        cutout: '60%'
    };

    return (
        <div className="attendance-charts-grid" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '20px', marginBottom: '24px' }}>
            <div style={{ background: 'var(--bg-panel)', borderRadius: '12px', padding: '20px', border: '1px solid var(--border-color)' }}>
                <h3 style={{ margin: '0 0 16px 0', fontSize: '1rem', color: 'var(--text-primary)' }}>Weekly Attendance Overview</h3>
                <div style={{ height: '280px' }}>
                    {weeklyChartData ? (
                        <Bar data={weeklyChartData} options={weeklyOptions} />
                    ) : (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>Loading...</div>
                    )}
                </div>
            </div>
            <div style={{ background: 'var(--bg-panel)', borderRadius: '12px', padding: '20px', border: '1px solid var(--border-color)' }}>
                <h3 style={{ margin: '0 0 16px 0', fontSize: '1rem', color: 'var(--text-primary)' }}>Department Attendance</h3>
                <div style={{ height: '280px' }}>
                    {deptChartData ? (
                        <Doughnut data={deptChartData} options={deptOptions} />
                    ) : (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>Loading...</div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default AttendanceCharts;
