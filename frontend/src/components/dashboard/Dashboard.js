import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, AreaChart, Area
} from 'recharts';
import {
  Users, UserCheck, UserX, Clock, Camera, AlertTriangle,
  Activity, Search, Filter, Download, ChevronLeft, ChevronRight,
  ShieldAlert, Server, Cpu, HardDrive, Maximize2, Loader2, FileText
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import FaceRecognitionAnalytics from './FaceRecognitionAnalytics';
import {
  fetchDashboardStats,
  fetchWeeklyAttendance,
  fetchDepartments,
  fetchEmployees,
  fetchAlerts,
  fetchLiveRecognitions
} from '../../services/api';
import { API_BASE_URL } from '../../utils/apiConfig';
import './Dashboard.css';

// --- COMPONENTS ---

// 1. Animated Number Component
const AnimatedNumber = ({ value }) => {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    if (value === undefined || value === null) {
      setDisplayValue(0);
      return;
    }

    let start = 0;
    const end = parseInt(value.toString().replace(/,/g, ''), 10);
    if (isNaN(end)) {
      setDisplayValue(value);
      return;
    }
    const duration = 1000;
    const increment = end / (duration / 16);

    const timer = setInterval(() => {
      start += increment;
      if (start >= end) {
        clearInterval(timer);
        setDisplayValue(end);
      } else {
        setDisplayValue(Math.floor(start));
      }
    }, 16);

    return () => clearInterval(timer);
  }, [value]);

  return <span>{displayValue.toLocaleString()}</span>;
};

// 2. Advanced KPI Card
const KPICard = ({ title, value, trend, trendValue, icon: Icon, colorClass, data = [], gradient }) => (
  <div
    className={`glass-panel p-5 flex flex-col justify-between hover:scale-[1.02] transition-all duration-300 relative overflow-hidden group`}
    style={{ borderColor: 'var(--border-color)' }}
  >
    {/* Background Glow */}
    <div className={`absolute -right-8 -top-8 w-32 h-32 rounded-full opacity-10 blur-3xl transition-transform group-hover:scale-150 bg-gradient-to-br ${gradient}`}></div>

    <div className="flex justify-between items-start z-10">
      <div className="flex-1">
        <p className="text-[10px] uppercase tracking-wider font-bold mb-1 opacity-70" style={{ color: 'var(--text-secondary)' }}>{title}</p>
        <h2 className={`text-3xl font-bold tracking-tight ${colorClass}`}>
          <AnimatedNumber value={value} />
        </h2>
        <div className="flex items-center mt-3">
          <span
            className={`text-[10px] font-bold ${trend === 'up' ? 'text-green-500' : 'text-red-500'} flex items-center px-2 py-0.5 rounded-full border border-current bg-opacity-10`}
            style={{ backgroundColor: trend === 'up' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)' }}
          >
            {trend === 'up' ? '↑' : '↓'} {trendValue}
          </span>
        </div>
      </div>

      {/* Advanced Icon Wrapper with prominent dynamic background */}
      <div className={`icon-wrapper-advanced ${colorClass} bg-current bg-opacity-20`}>
        <Icon size={22} strokeWidth={2} />
      </div>
    </div>

    <div className="h-12 mt-4 w-full z-10">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id={`color-${title.replace(/\s+/g, '')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={colorClass.replace('text-', '').split(' ')[0]} stopOpacity={0.3} />
              <stop offset="95%" stopColor={colorClass.replace('text-', '').split(' ')[0]} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="value" stroke="currentColor" fill={`url(#color-${title.replace(/\s+/g, '')})`} className={colorClass} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  </div>
);

// --- MAIN APP ---
export default function Dashboard({ setActiveTab }) {
  const { user: currentUser, company_id } = useAuthStore();

  // --- APPLICATION STATE ---
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  // Dashboard Data
  const [stats, setStats] = useState({
    present: 0, absent: 0, late: 0, total: 0, cameras: 0, alerts: 0,
    present_change: "0%", absent_change: "0%", late_change: "0%"
  });
  const [employees, setEmployees] = useState([]);
  const [weeklyData, setWeeklyData] = useState([]);
  const [departmentData, setDepartmentData] = useState([]);
  const [sparklines, setSparklines] = useState({
    present: [{ value: 0 }, { value: 5 }, { value: 3 }, { value: 8 }],
    absent: [{ value: 0 }, { value: 2 }, { value: 1 }, { value: 3 }],
    late: [{ value: 0 }, { value: 1 }, { value: 4 }, { value: 2 }],
    total: [{ value: 100 }, { value: 100 }, { value: 100 }],
    cameras: [{ value: 2 }, { value: 2 }, { value: 2 }],
    alerts: [{ value: 0 }, { value: 1 }, { value: 0 }]
  });

  // Real-time Data
  const [liveRecognitions, setLiveRecognitions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [cameras, setCameras] = useState([]);


  // --- API DATA FETCHING ---
  const loadData = async () => {
    try {
      const statsData = await fetchDashboardStats();
      const weekly = await fetchWeeklyAttendance();
      const depts = await fetchDepartments();
      const emp = await fetchEmployees();
      const alertData = await fetchAlerts();
      const live = await fetchLiveRecognitions();

      setStats({
        present: statsData.present_today || 0,
        absent: statsData.absent || 0,
        late: statsData.late || 0,
        total: statsData.total_employees || 0,
        cameras: statsData.cameras_active || 0,
        alerts: statsData.recognitions_today || 0,
        present_change: statsData.present_change || "0%",
        absent_change: statsData.absent_change || "0%",
        late_change: statsData.late_change || "0%"
      });

      // Update sparklines if backend provides trend data
      if (statsData.present_trend) {
        setSparklines(prev => ({ ...prev, present: statsData.present_trend }));
      }

      setWeeklyData(weekly);
      setDepartmentData(depts);
      setEmployees(emp);
      setAlerts(alertData);
      setLiveRecognitions(live);
    } catch (err) {
      console.error("Dashboard fetch error", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // refresh every 10s
    return () => clearInterval(interval);
  }, []);

  // --- REAL-TIME WEBSOCKET CONNECTION ---
  useEffect(() => {
    if (!company_id) return;

    const wsUrl = API_BASE_URL.replace('http', 'ws');
    const socket = new WebSocket(`${wsUrl}/ws/recognitions/${company_id}`);

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'RECOGNITION') {
          setLiveRecognitions(prev => [data.payload, ...prev].slice(0, 5));
          // Optionally update employee list if present
          setEmployees(prevEmp => prevEmp.map(emp =>
            emp.emp_id === data.payload.empId || emp.name === data.payload.name
              ? { ...emp, status: 'Present', punch_in: data.payload.time } : emp
          ));
        } else if (data.type === 'ALERT') {
          setAlerts(prev => [data.payload, ...prev].slice(0, 5));
          setStats(prev => ({ ...prev, alerts: prev.alerts + 1 }));
        }
      } catch (e) {
        console.error("WebSocket message error", e);
      }
    };

    socket.onerror = (error) => console.error("WebSocket error", error);

    return () => socket.close();
  }, [company_id]);

  // --- FILTERING ---
  const filteredEmployees = employees.filter(emp =>
    emp?.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    emp?.emp_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    emp?.department?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // --- EXPORT ---
  const exportCSV = () => {
    const csvHeaders = "EMP ID,NAME,DEPARTMENT,STATUS,PUNCH IN\n";
    const csvRows = employees.map(e =>
      `${e.emp_id || ''},${e.name || ''},${e.department || ''},${e.status || ''},${e.punch_in || ''}`
    ).join("\n");

    const blob = new Blob([csvHeaders + csvRows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = `attendance_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // --- RENDER LOADING STATE ---
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center flex-col gap-4" style={{ backgroundColor: 'var(--bg-main)' }}>
        <div className="relative">
          <div className="w-12 h-12 border-4 border-blue-200 rounded-full"></div>
          <div className="w-12 h-12 border-4 border-blue-600 rounded-full border-t-transparent animate-spin absolute top-0 left-0"></div>
        </div>
        <p className="font-medium animate-pulse" style={{ color: 'var(--text-secondary)' }}>Connecting to VisionAI Engine...</p>
      </div>
    );
  }

  // --- RENDER DASHBOARD ---
  return (
    <div className="min-h-screen bg-transparent text-gray-100 font-sans selection:bg-blue-200">

      {/* TOP NAVIGATION INFO (Internal to Dashboard) */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Dashboard Overview</h1>
          <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>Real-time attendance & security analytics</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden md:flex items-center gap-2 bg-green-900/30 px-3 py-1.5 rounded-full border border-green-100">
            <div className="w-2 h-2 bg-green-900/300 rounded-full animate-pulse"></div>
            <span className="text-xs font-semibold text-green-400">System Online</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={exportCSV}
              className="flex items-center gap-2 px-3 py-1.5 transition rounded-lg shadow-sm border text-xs font-semibold"
              style={{ color: 'var(--text-secondary)', backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-color)' }}
              title="Export attendance as CSV"
            >
              <Download size={16} /> Export CSV
            </button>
            <button
              onClick={async () => {
                try {
                  const response = await fetch(`${API_BASE_URL}/api/events/export/dashboard-pdf`, {
                    headers: { 'Authorization': `Bearer ${useAuthStore.getState().token}` }
                  });
                  if (!response.ok) throw new Error('Failed to generate PDF');
                  const blob = await response.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `dashboard_report_${new Date().toISOString().split('T')[0]}.pdf`;
                  a.click();
                } catch (err) {
                  console.error("Dashboard PDF Export Error", err);
                }
              }}
              className="flex items-center gap-2 px-3 py-1.5 transition rounded-lg shadow-sm border text-xs font-semibold"
              style={{ color: 'var(--text-secondary)', backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-color)' }}
              title="Export dashboard as premium PDF"
            >
              <FileText size={16} /> Export PDF
            </button>
            <button
              onClick={loadData}
              className="p-2 transition rounded-lg shadow-sm border"
              style={{ color: 'var(--text-secondary)', backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-color)' }}
            >
              <Activity size={20} />
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-8">

        {/* ROW 1: KPI CARDS */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-5">
          <KPICard title="Present Today" value={stats.present} trend="up" trendValue={stats.present_change} icon={UserCheck} colorClass="text-green-600" data={sparklines.present} gradient="from-green-400 to-emerald-500" />
          <KPICard title="Absent" value={stats.absent} trend="down" trendValue={stats.absent_change} icon={UserX} colorClass="text-red-500" data={sparklines.absent} gradient="from-red-400 to-rose-500" />
          <KPICard title="Late" value={stats.late} trend="up" trendValue={stats.late_change} icon={Clock} colorClass="text-orange-500" data={sparklines.late} gradient="from-orange-400 to-amber-500" />
          <KPICard title="Total Employees" value={stats.total} trend="up" trendValue="0%" icon={Users} colorClass="text-blue-400" data={sparklines.total} gradient="from-blue-400 to-indigo-500" />
          <KPICard title="Active Cameras" value={stats.cameras} trend="up" trendValue="0%" icon={Camera} colorClass="text-purple-600" data={sparklines.cameras} gradient="from-purple-400 to-violet-500" />
          <KPICard title="Alerts Today" value={stats.alerts} trend="up" trendValue="0" icon={AlertTriangle} colorClass="text-rose-600" data={sparklines.alerts} gradient="from-rose-500 to-red-600" />
        </div>

        {/* ROW 2: SYSTEM HEALTH */}
        <div className="grid grid-cols-1 gap-6">
          {/* System Health */}
          <div className="glass-panel p-6 flex flex-col justify-between lg:col-span-1">
            <h3 className="font-bold mb-4 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              <Server size={18} style={{ color: 'var(--text-secondary)' }} /> System Health
            </h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center p-3 rounded-xl border border-transparent hover:border-[var(--border-color)] transition-all" style={{ backgroundColor: 'var(--bg-input)' }}>
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg shadow-sm bg-blue-500/20"><Cpu size={16} className="text-blue-500" /></div>
                  <span className="text-xs font-bold uppercase tracking-tight" style={{ color: 'var(--text-primary)' }}>AI Inference Engine</span>
                </div>
                <span className="text-xs font-bold text-green-600 bg-green-100 px-2 py-1 rounded-md">Running</span>
              </div>
              <div className="flex justify-between items-center p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-input)' }}>
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg shadow-sm" style={{ backgroundColor: 'var(--bg-panel)' }}><Camera size={16} className="text-purple-500" /></div>
                  <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Camera Streams ({stats.cameras}/{stats.cameras})</span>
                </div>
                <span className="text-xs font-bold text-green-600 bg-green-100 px-2 py-1 rounded-md">Active</span>
              </div>
              <div className="flex justify-between items-center p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-input)' }}>
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg shadow-sm" style={{ backgroundColor: 'var(--bg-panel)' }}><HardDrive size={16} className="text-orange-500" /></div>
                  <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Database Sync</span>
                </div>
                <span className="text-xs font-bold text-green-600 bg-green-100 px-2 py-1 rounded-md">Connected</span>
              </div>

              <div className="pt-2">
                <div className="flex justify-between text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                  <span>GPU Usage</span>
                  <span>12%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
                  <div className="bg-gradient-to-r from-blue-500 to-indigo-600 h-2.5 rounded-full" style={{ width: '12%' }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ROW 3: ANALYTICS & ALERTS */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Weekly Chart */}
          <div className="glass-panel p-6 lg:col-span-2 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 blur-3xl -mr-16 -mt-16"></div>
            <h3 className="font-bold mb-6 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              <Activity size={18} className="text-blue-500" />
              <span className="text-xs uppercase tracking-widest">Weekly Attendance Analytics</span>
            </h3>
            <div className="h-[300px]">
              {weeklyData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={weeklyData} margin={{ top: 20, right: 30, left: 0, bottom: 5 }}>
                    <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#6b7280', fontSize: 12 }} dy={10} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b7280', fontSize: 12 }} />
                    <RechartsTooltip
                      cursor={{ fill: '#f3f4f6' }}
                      contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                    />
                    <Legend iconType="circle" wrapperStyle={{ paddingTop: '20px' }} />
                    <Bar dataKey="present" name="Present" stackId="a" fill="#22c55e" radius={[0, 0, 4, 4]} />
                    <Bar dataKey="late" name="Late" stackId="a" fill="#f97316" />
                    <Bar dataKey="absent" name="Absent" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full w-full flex items-center justify-center text-gray-400 text-sm border-2 border-dashed border-gray-800 rounded-xl">
                  Waiting for chart data...
                </div>
              )}
            </div>
          </div>

          {/* Activity & Insights Panel */}
          <div className="space-y-6">

            {/* Live Feed */}
            <div className="glass-panel p-5 min-h-[200px] relative overflow-hidden">
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-400 to-indigo-500 opacity-50"></div>
              <h3 className="font-bold text-[var(--text-primary)] mb-4 flex justify-between items-center">
                <span className="text-xs uppercase tracking-widest">Live Recognition Feed</span>
                <span className="flex h-3 w-3 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-blue-900/300"></span>
                </span>
              </h3>
              <div className="space-y-3">
                {liveRecognitions.length > 0 ? liveRecognitions.map(rec => (
                  <div key={rec.id} className="flex items-center gap-3 p-3 rounded-xl hover:bg-[var(--bg-hover)] transition-all border border-transparent hover:border-[var(--border-color)] group">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-xs shadow-inner relative overflow-hidden ${rec.imgColor || 'bg-gray-400'}`}>
                      <div className="absolute inset-0 bg-black/10"></div>
                      <span className="relative z-10">{rec.name === 'Unknown Person' ? '?' : rec?.name?.charAt(0) || 'U'}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-bold truncate group-hover:text-[var(--primary-color)] transition-colors ${rec.status === 'Alert' ? 'text-red-600' : 'text-[var(--text-primary)]'}`}>{rec.name}</p>
                      <p className="text-xs text-gray-400 flex items-center gap-1">
                        {rec.time} • {rec.camera}
                      </p>
                    </div>
                    <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${rec.status === 'Recognized' ? 'bg-green-100 text-green-400' : 'bg-red-100 text-red-400 animate-pulse'
                      }`}>
                      {rec.status}
                    </span>
                  </div>
                )) : (
                  <div className="text-center py-8 text-sm text-gray-400">Listening for recognitions...</div>
                )}
              </div>
            </div>

            {/* Alerts Panel */}
            <div className="p-5 rounded-2xl shadow-sm border min-h-[150px] relative overflow-hidden" style={{ backgroundColor: 'rgba(225, 29, 72, 0.05)', borderColor: 'rgba(225, 29, 72, 0.2)' }}>
              <div className="absolute -right-4 -bottom-4 w-24 h-24 bg-rose-500/10 blur-2xl rounded-full"></div>
              <h3 className="font-bold text-rose-500 mb-3 flex items-center gap-2">
                <ShieldAlert size={18} />
                <span className="text-xs uppercase tracking-widest">System Alerts</span>
              </h3>
              <div className="space-y-2">
                {alerts.length > 0 ? alerts.map(alert => (
                  <div key={alert.id} className="p-3 rounded-xl border-l-4 border-rose-500 shadow-sm text-sm" style={{ backgroundColor: 'var(--bg-input)' }}>
                    <div className="flex justify-between font-semibold text-gray-100 mb-1">
                      <span>{alert.type}</span>
                      <span className="text-xs text-gray-400 font-normal">{alert.time}</span>
                    </div>
                    <p className="text-xs text-gray-300 flex items-center gap-1">
                      <Camera size={12} /> {alert.location}
                    </p>
                  </div>
                )) : (
                  <div className="text-center py-4 text-sm text-rose-400/70">No active alerts</div>
                )}
              </div>
            </div>

          </div>
        </div>

        {/* PERSISTED COMPONENT AS REQUESTED */}
        <div className="pt-8">
          <FaceRecognitionAnalytics />
        </div>
      </div>

      <style dangerouslySetInnerHTML={{
        __html: `
        @keyframes fade-in-down {
          0% { opacity: 0; transform: translateY(-10px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-in-down { animation: fade-in-down 0.4s ease-out forwards; }
      `}} />
    </div>
  );
}
