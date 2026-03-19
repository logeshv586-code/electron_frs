import React from 'react';
import useAuthStore from '../../store/authStore';
import {
  LayoutDashboard,
  Users,
  Camera,
  Image,
  Bell,
  ScanFace,
  Video,
  MonitorPlay,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Menu,
  Settings,
  Palette,
  CalendarDays,
  CalendarCheck,
  Database
} from 'lucide-react';
import './MainLayout.css';

const MainLayout = ({ children, activeTab, onTabChange }) => {
  const { user, logout, isLicenseExpired } = useAuthStore();
  const [collapsed, setCollapsed] = React.useState(false);
  const [expandedTabs, setExpandedTabs] = React.useState({});

  const toggleExpanded = (tabId) => {
    setExpandedTabs(prev => ({ ...prev, [tabId]: !prev[tabId] }));
  };

  const themes = [
    { id: 'default', label: 'Dark Enterprise', color: '#0b1120' },
    { id: 'light', label: 'Light Blue', color: '#ffffff' },
    { id: 'navy', label: 'Navy Professional', color: '#1a365d' },
    { id: 'phoenix', label: 'Phoenix Orange', color: '#f97316' },
    { id: 'nexus', label: 'Nexus Cyberpunk', color: '#06b6d4' },
  ];

  const [theme, setTheme] = React.useState(() => {
    const saved = localStorage.getItem('theme');
    return themes.some(t => t.id === saved) ? saved : 'default';
  });

  // Transition effect for theme changes
  React.useEffect(() => {
    document.body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
    const timer = setTimeout(() => {
      document.body.style.transition = '';
    }, 300);
    return () => clearTimeout(timer);
  }, [theme]);
  const [showThemeMenu, setShowThemeMenu] = React.useState(false);

  React.useEffect(() => {
    if (theme === 'default') {
      document.body.removeAttribute('data-theme');
    } else {
      document.body.setAttribute('data-theme', theme);
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={20} /> },
    { id: 'companies', label: 'Companies', icon: <ScanFace size={20} /> }, // Added Companies
    { id: 'registration', label: 'Employees', icon: <Users size={20} /> }, // Renamed to Employees
    {
      id: 'attendance',
      label: 'Attendance',
      icon: <CalendarCheck size={20} />,
      subItems: [
        { id: 'attendance-report', label: 'Attendance Report' },
        { id: 'day-report', label: 'Day Report' },
        { id: 'week-report', label: 'Week Report' },
        { id: 'month-report', label: 'Month Report' },
      ]
    },
    { id: 'holiday-calendar', label: 'Holiday Calendar', icon: <CalendarDays size={20} /> },
    { id: 'gallery', label: 'Gallery', icon: <Image size={20} /> },
    { id: 'events', label: 'Events', icon: <Bell size={20} /> },
    { id: 'camera', label: 'Cameras', icon: <Camera size={20} /> }, // Renamed to Cameras
    { id: 'stream-viewer', label: 'Stream Viewer', icon: <MonitorPlay size={20} /> },
    { id: 'video', label: 'Video Processing', icon: <Video size={20} /> },
    { id: 'users', label: 'User Management', icon: <Users size={20} /> },
    { id: 'settings', label: 'Settings', icon: <Settings size={20} /> },
    { id: 'backup', label: 'Backup Mgmt', icon: <Database size={20} /> },
  ];

  const visibleTabs = tabs.filter(tab => {
    const userRole = user?.role ? user.role.toLowerCase() : '';
    if (user?.assigned_menus && user.assigned_menus.length > 0) {
      const normalizedMenus = user.assigned_menus.map(m => {
        if (m === 'cameras') return 'camera';
        if (m === 'admin') return 'users';
        if (m === 'backupmgmt') return 'backup';
        return m;
      });
      if (['admin', 'superadmin'].includes(userRole)) {
        if (!normalizedMenus.includes('attendance')) normalizedMenus.push('attendance');
        if (!normalizedMenus.includes('backup')) normalizedMenus.push('backup');
      }
      return normalizedMenus.includes(tab.id);
    }
    if (userRole === 'superadmin') return ['dashboard', 'companies', 'registration', 'attendance', 'holiday-calendar', 'gallery', 'events', 'camera', 'stream-viewer', 'video', 'users', 'settings', 'backup'].includes(tab.id);
    if (userRole === 'admin') return ['dashboard', 'registration', 'attendance', 'holiday-calendar', 'gallery', 'events', 'camera', 'stream-viewer', 'video', 'users', 'settings', 'backup'].includes(tab.id);
    return ['dashboard'].includes(tab.id);
  });

  return (
    <div className={`main-layout ${collapsed ? 'collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo-container">
            {!collapsed && <span className="logo-text">frs</span>}
          </div>
          <button
            className="collapse-btn"
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        <div className="user-profile-section">
          <div className="user-avatar">
            {user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
          {!collapsed && (
            <div className="user-info">
              <span className="user-name">{user?.username || 'User'}</span>
              <span className="user-role-badge">{user?.role || 'Guest'}</span>
            </div>
          )}
        </div>

        <nav className="sidebar-nav">
          {visibleTabs.map(tab => (
            <div key={tab.id} className="nav-item-container">
              <button
                className={`nav-item ${activeTab === tab.id || (tab.subItems && tab.subItems.some(sub => sub.id === activeTab)) ? 'active' : ''}`}
                onClick={() => {
                  if (tab.subItems) {
                    toggleExpanded(tab.id);
                  } else {
                    onTabChange(tab.id);
                  }
                }}
                title={collapsed ? tab.label : ''}
              >
                <div className="nav-item-content">
                  <span className="nav-icon">{tab.icon}</span>
                  {!collapsed && <span className="nav-label">{tab.label}</span>}
                </div>
                {!collapsed && tab.subItems && (
                  <span className="nav-chevron">
                    <ChevronDown size={16} style={{ transform: expandedTabs[tab.id] ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }} />
                  </span>
                )}
                {activeTab === tab.id && !collapsed && !tab.subItems && <div className="active-indicator" />}
              </button>

              {!collapsed && tab.subItems && expandedTabs[tab.id] && (
                <div className="sub-nav">
                  {tab.subItems.map(subItem => (
                    <button
                      key={subItem.id}
                      className={`sub-nav-item ${activeTab === subItem.id ? 'active' : ''}`}
                      onClick={() => onTabChange(subItem.id)}
                    >
                      <span className="sub-nav-indicator"></span>
                      <span className="nav-label">{subItem.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button className="logout-btn" onClick={logout} title={collapsed ? "Logout" : ""}>
            <LogOut size={20} />
            {!collapsed && <span>Logout</span>}
          </button>
        </div>
      </aside>

      <main className="content-area">
        <header className="top-header">
          <div className="header-left">
            <button className="mobile-menu-btn">
              <Menu size={24} />
            </button>
            <h1 className="page-title">
              {tabs.find(t => t.id === activeTab)?.label || 'Dashboard'}
            </h1>
          </div>
          <div className="header-right">
            <div className="theme-switcher-container">
              <button
                className="theme-toggle-btn"
                onClick={() => setShowThemeMenu(!showThemeMenu)}
                title="Change Theme"
              >
                <Palette size={20} />
              </button>

              {showThemeMenu && (
                <div className="theme-menu">
                  <div className="theme-menu-header">Select Theme</div>
                  {themes.map(t => (
                    <button
                      key={t.id}
                      className={`theme-option ${theme === t.id ? 'active' : ''}`}
                      onClick={() => {
                        setTheme(t.id);
                        setShowThemeMenu(false);
                      }}
                    >
                      <div className="theme-preview" style={{ backgroundColor: t.color }}></div>
                      <span className="theme-label">{t.label}</span>
                      {theme === t.id && <div className="theme-check">✓</div>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="system-status">
              <span className="status-dot online"></span>
              <span className="status-text">System Online</span>
            </div>
          </div>
        </header>

        {user?.role === 'Admin' && isLicenseExpired() && (
          <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444', margin: '12px 16px', borderRadius: 8 }}>
            Licence expired. Please contact SuperAdmin to renew access.
          </div>
        )}

        <div className="content-wrapper">
          <div key={activeTab} className="animate-slide-up">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
};

export default MainLayout;
