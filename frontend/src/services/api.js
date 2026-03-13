import { API_BASE_URL } from '../utils/apiConfig';

/**
 * Enhanced API Service for Dashboard
 * All calls include the Authorization header for multi-tenancy support.
 */

const getHeaders = () => {
    const authData = localStorage.getItem('auth-storage');
    let token = '';
    if (authData) {
        try {
            const parsed = JSON.parse(authData);
            token = parsed.state?.token || '';
        } catch (e) {
            console.error("Error parsing auth storage", e);
        }
    }
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };
};

export const fetchDashboardStats = async () => {
    const res = await fetch(`${API_BASE_URL}/api/events/dashboard-stats`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch dashboard stats');
    return res.json();
};

export const fetchWeeklyAttendance = async () => {
    const res = await fetch(`${API_BASE_URL}/api/events/attendance/weekly`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch weekly attendance');
    const data = await res.json();
    return data.weekly || [];
};

export const fetchDepartments = async () => {
    const res = await fetch(`${API_BASE_URL}/api/events/attendance/department-stats`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch department stats');
    const data = await res.json();
    // Transform object to array format expected by the pie chart
    // Example: { "IT": { "present": 5, "total": 10 } } -> [{ name: "IT", value: 50, color: "#..." }]
    if (data.departments) {
        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#0ea5e9', '#f97316', '#64748b'];
        return Object.entries(data.departments).map(([name, stats], index) => ({
            name,
            value: stats.total > 0 ? Math.round((stats.present / stats.total) * 100) : 0,
            color: colors[index % colors.length]
        }));
    }
    return [];
};

export const fetchEmployees = async () => {
    const res = await fetch(`${API_BASE_URL}/api/events/attendance`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch employees');
    const data = await res.json();
    return data.attendance || [];
};

export const fetchAlerts = async () => {
    // Use filter endpoint for unknown faces as "alerts"
    const res = await fetch(`${API_BASE_URL}/api/events/filter?face_type=unknown`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch alerts');
    const data = await res.json();
    // Transform to alerts format
    return data.slice(0, 5).map(event => ({
        id: event.timestamp + event.camera,
        type: 'Unknown Person',
        time: new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        location: event.camera
    }));
};

export const fetchLiveRecognitions = async () => {
    // Use filter endpoint for recent known face recognitions as initial state
    const res = await fetch(`${API_BASE_URL}/api/events/filter?face_type=known`, {
        headers: getHeaders()
    });
    if (!res.ok) throw new Error('Failed to fetch live recognitions');
    const data = await res.json();
    return data.slice(0, 5).map(event => ({
        id: event.timestamp + event.name,
        name: event.name,
        time: new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        camera: event.camera,
        status: 'Recognized',
        imgColor: 'bg-blue-500' // Default color
    }));
};
