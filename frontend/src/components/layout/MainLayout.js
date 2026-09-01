import React from 'react';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import {
  LayoutDashboard,
  Users,
  Camera,
  ScanFace,
  Video,
  MonitorPlay,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Menu,
  X,
  Settings,
  Palette,
  CalendarDays,
  CalendarCheck,
  Database,
  Building2,
  ShieldCheck,
  Circle,
} from 'lucide-react';
import './MainLayout.css';

const ACCENTS = [
  { id: 'sapphire', label: 'Sapphire', description: 'Commercial blue', color: '#2563eb' },
  { id: 'teal', label: 'Teal', description: 'Security monitoring', color: '#0f8b83' },
  { id: 'indigo', label: 'Indigo', description: 'Enterprise', color: '#4f46e5' },
  { id: 'graphite', label: 'Graphite', description: 'Corporate neutral', color: '#475569' },
];

const expandMenuIds = (source = []) => {
  const result = new Set();
  source.forEach((raw) => {
    const menu = String(raw || '').trim().toLowerCase();
    if (!menu) return;
    if (menu === 'cameras') result.add('camera');
    else if (menu === 'admin') result.add('users');
    else if (menu === 'backupmgmt') result.add('backup');
    else if (menu === 'attendance') {
      result.add('attendance-report');
      result.add('day-report');
      result.add('week-report');
      result.add('month-report');
    } else {
      result.add(menu);
    }
  });
  return result;
};

const MainLayout = ({ children, activeTab, onTabChange }) => {
  const { user, token, logout, isLicenseExpired } = useAuthStore();
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [expandedTabs, setExpandedTabs] = React.useState({ matchingGroup: true, reportsGroup: true });
  const [showAccentMenu, setShowAccentMenu] = React.useState(false);
  const [accent, setAccent] = React.useState(() => {
    const saved = localStorage.getItem('frs-accent');
    return ACCENTS.some((item) => item.id === saved) ? saved : 'sapphire';
  });
  const [system, setSystem] = React.useState({ online: true, activeCameras: 0, totalCameras: 0 });

  React.useEffect(() => {
    document.documentElement.setAttribute('data-accent', accent);
    document.body.removeAttribute('data-theme');
    localStorage.setItem('frs-accent', accent);
    localStorage.removeItem('theme');
  }, [accent]);

  React.useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;

    const loadStatus = async () => {
      const headers = { Authorization: `Bearer ${token}` };
      try {
        const [statusResponse, cameraResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/status`, { headers }),
          fetch(`${API_BASE_URL}/api/collections/cameras?page=1&per_page=1`, { headers }),
        ]);
        const cameras = cameraResponse.ok ? await cameraResponse.json() : {};
        if (!cancelled) {
          setSystem({
            online: statusResponse.ok,
            activeCameras: Number(cameras.active_cameras || 0),
            totalCameras: Number(cameras.total_cameras || 0),
          });
        }
      } catch (error) {
        if (!cancelled) setSystem((previous) => ({ ...previous, online: false }));
      }
    };

    loadStatus();
    const timer = window.setInterval(loadStatus, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [token]);

  const tabs = React.useMemo(() => [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'companies', label: 'Companies', icon: Building2, superAdminOnly: true },
    { id: 'registration', label: 'Employees', icon: Users },
    {
      id: 'matchingGroup',
      label: 'Matching',
      icon: ScanFace,
      subItems: [
        { id: 'matching', label: 'Face Matching' },
        { id: 'gallery', label: 'Face Gallery' },
        { id: 'events', label: 'Recognition Events' },
      ],
    },
    {
      id: 'reportsGroup',
      label: 'Reports',
      icon: CalendarCheck,
      subItems: [
        { id: 'attendance-report', label: 'Attendance' },
        { id: 'day-report', label: 'Daily Report' },
        { id: 'week-report', label: 'Weekly Report' },
        { id: 'month-report', label: 'Monthly Report' },
      ],
    },
    { id: 'holiday-calendar', label: 'Holiday Calendar', icon: CalendarDays },
    { id: 'camera', label: 'Cameras', icon: Camera },
    { id: 'stream-viewer', label: 'Live View', icon: MonitorPlay },
    { id: 'video', label: 'Video Processing', icon: Video },
    { id: 'users', label: 'User Management', icon: Users },
    { id: 'settings', label: 'Settings', icon: Settings },
    { id: 'backup', label: 'Backup', icon: Database },
  ], []);

  const normalizedAssignedMenus = React.useMemo(
    () => expandMenuIds(Array.isArray(user?.assigned_menus) ? user.assigned_menus : []),
    [user?.assigned_menus],
  );

  const role = String(user?.role || '').toLowerCase();
  const defaultAccess = React.useMemo(() => {
    if (role === 'superadmin') {
      return new Set(['dashboard', 'companies', 'registration', 'matching', 'gallery', 'events', 'attendance-report', 'day-report', 'week-report', 'month-report', 'holiday-calendar', 'camera', 'stream-viewer', 'video', 'users', 'settings', 'backup']);
    }
    if (role === 'admin') {
      return new Set(['dashboard', 'registration', 'matching', 'gallery', 'events', 'attendance-report', 'day-report', 'week-report', 'month-report', 'camera', 'stream-viewer', 'video', 'users', 'settings', 'backup']);
    }
    if (role === 'supervisor') {
      return new Set(['dashboard', 'events', 'attendance-report', 'day-report', 'week-report', 'month-report', 'camera', 'stream-viewer']);
    }
    return new Set(['dashboard']);
  }, [role]);

  const hasExplicitMenus = normalizedAssignedMenus.size > 0;
  const canAccess = React.useCallback((tabId) => {
    if (role === 'superadmin') return true;
    return hasExplicitMenus ? normalizedAssignedMenus.has(tabId) : defaultAccess.has(tabId);
  }, [defaultAccess, hasExplicitMenus, normalizedAssignedMenus, role]);

  const visibleTabs = tabs
    .filter((tab) => !tab.superAdminOnly || role === 'superadmin')
    .map((tab) => {
      if (!tab.subItems) return tab;
      return { ...tab, subItems: tab.subItems.filter((item) => canAccess(item.id)) };
    })
    .filter((tab) => tab.subItems ? tab.subItems.length > 0 : canAccess(tab.id));

  React.useEffect(() => {
    const directlyVisible = visibleTabs.some((tab) => tab.id === activeTab || tab.subItems?.some((item) => item.id === activeTab));
    if (!directlyVisible && visibleTabs.length > 0) {
      const first = visibleTabs[0];
      onTabChange(first.subItems?.[0]?.id || first.id);
    }
  }, [activeTab, onTabChange, visibleTabs]);

  const findLabel = () => {
    for (const tab of tabs) {
      if (tab.id === activeTab) return tab.label;
      const child = tab.subItems?.find((item) => item.id === activeTab);
      if (child) return child.label;
    }
    return 'Dashboard';
  };

  const selectTab = (tabId) => {
    if (!canAccess(tabId) && role !== 'superadmin') return;
    onTabChange(tabId);
    setMobileOpen(false);
  };

  const toggleExpanded = (tabId) => {
    setExpandedTabs((previous) => ({ ...previous, [tabId]: !previous[tabId] }));
  };

  const handleLogout = () => {
    setMobileOpen(false);
    logout();
  };

  return (
    <div className={`main-layout ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
      {mobileOpen && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}

      <aside className="sidebar" aria-label="Application navigation">
        <div className="sidebar-header">
          <button className="brand-block" onClick={() => selectTab('dashboard')} title="Face Recognition">
            <span className="brand-mark"><ScanFace size={19} strokeWidth={2.1} /></span>
            {!collapsed && (
              <span className="brand-copy">
                <strong>Face Recognition</strong>
                <small>Attendance System</small>
              </span>
            )}
          </button>
          <button className="mobile-close-btn" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X size={18} /></button>
          <button className="collapse-btn" onClick={() => setCollapsed((value) => !value)} title={collapsed ? 'Expand navigation' : 'Collapse navigation'}>
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        <div className="user-profile-section">
          <div className="user-avatar">{user?.username?.charAt(0)?.toUpperCase() || 'U'}</div>
          {!collapsed && (
            <div className="user-info">
              <span className="user-name">{user?.username || 'User'}</span>
              <span className="user-role-line"><ShieldCheck size={12} /> {user?.role || 'User'}</span>
            </div>
          )}
        </div>

        <nav className="sidebar-nav">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon;
            const childActive = tab.subItems?.some((item) => item.id === activeTab);
            const active = activeTab === tab.id || childActive;
            const expanded = !!expandedTabs[tab.id];
            return (
              <div key={tab.id} className="nav-item-container">
                <button
                  className={`nav-item ${active ? 'active' : ''}`}
                  onClick={() => tab.subItems ? toggleExpanded(tab.id) : selectTab(tab.id)}
                  title={collapsed ? tab.label : undefined}
                >
                  <span className="nav-icon"><Icon size={17} strokeWidth={1.9} /></span>
                  {!collapsed && <span className="nav-label">{tab.label}</span>}
                  {!collapsed && tab.subItems && <ChevronDown className={`nav-chevron ${expanded ? 'expanded' : ''}`} size={14} />}
                </button>
                {!collapsed && tab.subItems && expanded && (
                  <div className="sub-nav">
                    {tab.subItems.map((item) => (
                      <button key={item.id} className={`sub-nav-item ${activeTab === item.id ? 'active' : ''}`} onClick={() => selectTab(item.id)}>
                        <span className="sub-nav-line" />
                        <span>{item.label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-system-card">
          {!collapsed && (
            <>
              <div className="sidebar-system-row">
                <span className={`system-dot ${system.online ? 'online' : 'offline'}`} />
                <span>{system.online ? 'System connected' : 'Backend offline'}</span>
              </div>
              <div className="sidebar-camera-row">
                <Camera size={13} />
                <span>{system.activeCameras}/{system.totalCameras} cameras active</span>
              </div>
            </>
          )}
        </div>

        <div className="sidebar-footer">
          <button className="logout-btn" onClick={handleLogout} title={collapsed ? 'Sign out' : undefined}>
            <LogOut size={16} />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      <main className="content-area">
        <header className="top-header">
          <div className="header-left">
            <button className="mobile-menu-btn" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={19} /></button>
            <div className="page-heading">
              <h1 className="page-title">{findLabel()}</h1>
              <span className="page-context">Face Recognition System</span>
            </div>
          </div>

          <div className="header-right">
            <div className="header-status" title="Backend and camera status">
              <span className={`system-dot ${system.online ? 'online' : 'offline'}`} />
              <span className="status-copy">{system.online ? 'Connected' : 'Offline'}</span>
              <span className="status-divider" />
              <Camera size={14} />
              <span>{system.activeCameras}/{system.totalCameras}</span>
            </div>

            <div className="accent-switcher">
              <button className="accent-toggle-btn" onClick={() => setShowAccentMenu((value) => !value)} aria-expanded={showAccentMenu} title="Accent color">
                <Palette size={17} />
              </button>
              {showAccentMenu && (
                <div className="accent-menu">
                  <div className="accent-menu-header">
                    <strong>Accent color</strong>
                    <span>Light appearance stays fixed</span>
                  </div>
                  {ACCENTS.map((item) => (
                    <button
                      key={item.id}
                      className={`accent-option ${accent === item.id ? 'active' : ''}`}
                      onClick={() => { setAccent(item.id); setShowAccentMenu(false); }}
                    >
                      <span className="accent-swatch" style={{ backgroundColor: item.color }} />
                      <span className="accent-option-copy"><strong>{item.label}</strong><small>{item.description}</small></span>
                      {accent === item.id && <Circle size={8} fill="currentColor" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </header>

        {user?.role !== 'SuperAdmin' && isLicenseExpired() && (
          <div className="license-alert">Company licence expired. Contact your provider to renew access.</div>
        )}

        <div className="content-wrapper">
          <div key={activeTab} className="animate-slide-up content-page">{children}</div>
        </div>
      </main>
    </div>
  );
};

export default MainLayout;
