import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import {
  Database,
  Download,
  RotateCcw,
  Eye,
  Trash2,
  Clock,
  FileText,
  AlertTriangle,
  CheckCircle,
  XCircle,
  X,
  RefreshCw,
  Shield,
  HardDrive,
  Activity,
  Users
} from 'lucide-react';
import './BackupDashboard.css';

const BACKUP_API = `${API_BASE_URL}/api/backup`;

const BackupDashboard = () => {
  const { token } = useAuthStore();
  const [activeView, setActiveView] = useState('backups');
  const [backups, setBackups] = useState([]);
  const [logs, setLogs] = useState([]);
  const [deletedTenants, setDeletedTenants] = useState([]);
  const [loading, setLoading] = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null); // { type, text }
  const [previewData, setPreviewData] = useState(null);
  const [restoreConfirm, setRestoreConfirm] = useState(null); // { type, filename, tenantId }
  const [restoreOverwrite, setRestoreOverwrite] = useState(false);
  const [restoreLoading, setRestoreLoading] = useState(false);
  const [tenantIdInput, setTenantIdInput] = useState('');

  const headers = { Authorization: `Bearer ${token}` };

  // ─────────────── Fetch Data ───────────────

  const fetchBackups = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${BACKUP_API}/list`, { headers });
      setBackups(res.data.backups || []);
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Failed to load backups: ' + (err.response?.data?.detail || err.message) });
    } finally {
      setLoading(false);
    }
  }, [token]);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await axios.get(`${BACKUP_API}/logs`, { headers });
      setLogs(res.data.logs || []);
    } catch (err) {
      console.error('Failed to load logs', err);
    }
  }, [token]);

  const fetchDeletedTenants = useCallback(async () => {
    try {
      const res = await axios.get(`${BACKUP_API}/deleted-tenants`, { headers });
      setDeletedTenants(res.data.deleted_tenants || []);
    } catch (err) {
      console.error('Failed to load deleted tenants', err);
    }
  }, [token]);

  useEffect(() => {
    fetchBackups();
  }, [fetchBackups]);

  useEffect(() => {
    if (activeView === 'logs') fetchLogs();
    if (activeView === 'deleted') fetchDeletedTenants();
  }, [activeView]);

  // ─────────────── Actions ───────────────

  const handleTriggerBackup = async () => {
    setTriggerLoading(true);
    setStatusMessage(null);
    try {
      const res = await axios.post(`${BACKUP_API}/trigger`, {}, { headers });
      setStatusMessage({
        type: 'success',
        text: `Backup created: ${res.data.filename} (${res.data.total_keys} keys, ${res.data.duration_seconds?.toFixed(1)}s)`
      });
      fetchBackups();
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Backup failed: ' + (err.response?.data?.detail || err.message) });
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleDownload = async (filename) => {
    try {
      const res = await axios.get(`${BACKUP_API}/download/${filename}`, {
        headers,
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Download failed: ' + (err.response?.data?.detail || err.message) });
    }
  };

  const handlePreview = async (filename) => {
    try {
      const res = await axios.get(`${BACKUP_API}/preview/${filename}`, { headers });
      setPreviewData(res.data);
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Preview failed: ' + (err.response?.data?.detail || err.message) });
    }
  };

  const handleRestore = async () => {
    if (!restoreConfirm) return;
    setRestoreLoading(true);
    try {
      const endpoint = restoreConfirm.type === 'full' ? '/restore/full' : '/restore/tenant';
      const body = {
        filename: restoreConfirm.filename,
        overwrite: restoreOverwrite,
        confirm: true,
        ...(restoreConfirm.type === 'tenant' && { tenant_id: restoreConfirm.tenantId })
      };
      const res = await axios.post(`${BACKUP_API}${endpoint}`, body, { headers });
      setStatusMessage({
        type: 'success',
        text: `Restore complete: ${res.data.restored_keys} keys restored, ${res.data.skipped_keys} skipped`
      });
      setRestoreConfirm(null);
      setRestoreOverwrite(false);
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Restore failed: ' + (err.response?.data?.detail || err.message) });
    } finally {
      setRestoreLoading(false);
    }
  };

  const handleRetention = async () => {
    try {
      const res = await axios.post(`${BACKUP_API}/enforce-retention`, {}, { headers });
      setStatusMessage({
        type: 'info',
        text: `Retention enforced: ${res.data.deleted_count} old backups removed, ${res.data.kept} kept`
      });
      fetchBackups();
    } catch (err) {
      setStatusMessage({ type: 'error', text: 'Retention failed: ' + (err.response?.data?.detail || err.message) });
    }
  };

  // ─────────────── Render ───────────────

  const renderBackupsList = () => {
    if (loading) {
      return (
        <div className="backup-empty">
          <div className="backup-spinner" style={{ margin: '0 auto 16px' }}></div>
          <p>Loading backups...</p>
        </div>
      );
    }

    if (backups.length === 0) {
      return (
        <div className="backup-empty">
          <div className="backup-empty-icon"><Database size={28} /></div>
          <h4>No Backups Found</h4>
          <p>Click "Trigger Backup" to create your first backup.</p>
        </div>
      );
    }

    return (
      <div className="table-responsive">
        <table className="backup-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Date</th>
              <th>Size</th>
              <th>Keys</th>
              <th>Tenants</th>
              <th>Errors</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {backups.map((b, i) => (
              <tr key={i}>
                <td className="filename">{b.filename}</td>
                <td>{b.created_at !== 'N/A' ? new Date(b.created_at).toLocaleString() : b.modified_at ? new Date(b.modified_at).toLocaleString() : 'N/A'}</td>
                <td>{b.file_size_readable}</td>
                <td><span className="badge badge-info">{b.total_keys}</span></td>
                <td><span className="badge badge-success">{b.tenant_ids?.length || 0}</span></td>
                <td>
                  {b.errors_count > 0 ? (
                    <span className="badge badge-warning">{b.errors_count}</span>
                  ) : (
                    <span className="badge badge-success">0</span>
                  )}
                </td>
                <td>
                  <div className="backup-actions">
                    <button className="btn-icon-sm" title="Preview" onClick={() => handlePreview(b.filename)}>
                      <Eye size={14} />
                    </button>
                    <button className="btn-icon-sm" title="Download" onClick={() => handleDownload(b.filename)}>
                      <Download size={14} />
                    </button>
                    <button
                      className="btn-icon-sm"
                      title="Restore Full"
                      onClick={() => setRestoreConfirm({ type: 'full', filename: b.filename })}
                    >
                      <RotateCcw size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderTenantRestore = () => (
    <div className="backup-card">
      <div className="backup-card-header">
        <h3><Users size={18} /> Tenant-Level Restore</h3>
      </div>
      <div className="backup-card-body">
        <p style={{ color: 'var(--text-secondary, #94a3b8)', marginBottom: 16, fontSize: '0.85rem' }}>
          Restore a specific tenant's data from a backup. Only keys matching <code>tenant:&#123;id&#125;:*</code> will be restored.
        </p>
        {backups.length === 0 ? (
          <p style={{ color: '#64748b' }}>No backups available. Create a backup first.</p>
        ) : (
          backups.map((b, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, padding: '10px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(148,163,184,0.06)' }}>
              <FileText size={16} style={{ color: '#3b82f6', flexShrink: 0 }} />
              <span style={{ flex: 1, fontSize: '0.85rem', fontWeight: 600 }}>{b.filename}</span>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                {b.tenant_ids?.join(', ') || 'N/A'}
              </span>
              <div className="tenant-input-row" style={{ marginBottom: 0, flex: '0 0 auto' }}>
                <input
                  type="text"
                  placeholder="Tenant ID"
                  value={tenantIdInput}
                  onChange={(e) => setTenantIdInput(e.target.value)}
                  style={{ width: 120 }}
                />
                <button
                  className="btn-restore-sm"
                  disabled={!tenantIdInput.trim()}
                  onClick={() => setRestoreConfirm({ type: 'tenant', filename: b.filename, tenantId: tenantIdInput.trim() })}
                >
                  <RotateCcw size={12} /> Restore
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );

  const renderLogs = () => (
    <div className="backup-card">
      <div className="backup-card-header">
        <h3><Clock size={18} /> Backup Audit Logs</h3>
        <button className="btn-icon-sm" onClick={fetchLogs} title="Refresh"><RefreshCw size={14} /></button>
      </div>
      <div className="backup-card-body">
        {logs.length === 0 ? (
          <div className="backup-empty">
            <div className="backup-empty-icon"><Activity size={28} /></div>
            <h4>No Logs Yet</h4>
            <p>Backup operations will appear here.</p>
          </div>
        ) : (
          logs.slice().reverse().map((log, i) => (
            <div className="log-entry" key={i}>
              <div className="log-entry-content">
                <div className={`log-entry-type ${log.type}`}>
                  {log.type === 'scheduled' ? '⏱ Scheduled' : '👤 Manual'} — {log.action || log.status || 'backup'}
                </div>
                <div className="log-entry-details">
                  {log.filename && <span>File: {log.filename} · </span>}
                  {log.total_keys !== undefined && <span>Keys: {log.total_keys} · </span>}
                  {log.duration_seconds !== undefined && <span>Duration: {log.duration_seconds?.toFixed(1)}s · </span>}
                  {log.user && <span>By: {log.user} · </span>}
                  {log.error && <span style={{ color: '#ef4444' }}>Error: {log.error}</span>}
                  {log.status && <span>Status: <strong>{log.status}</strong></span>}
                </div>
              </div>
              <div className="log-entry-time">
                {log.timestamp || log.start_time ? new Date(log.timestamp || log.start_time).toLocaleString() : 'N/A'}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );

  const renderDeletedTenants = () => (
    <div className="backup-card">
      <div className="backup-card-header">
        <h3><Shield size={18} /> Recoverable Deleted Tenants</h3>
        <button className="btn-icon-sm" onClick={fetchDeletedTenants} title="Refresh"><RefreshCw size={14} /></button>
      </div>
      <div className="backup-card-body">
        {deletedTenants.length === 0 ? (
          <div className="backup-empty">
            <div className="backup-empty-icon"><CheckCircle size={28} /></div>
            <h4>All Tenants Active</h4>
            <p>No deleted tenants found in backup history.</p>
          </div>
        ) : (
          deletedTenants.map((t, i) => (
            <div className="deleted-tenant-card" key={i}>
              <div className="deleted-tenant-info">
                <h4>Tenant: {t.tenant_id}</h4>
                <p>Available in {t.backup_count} backup(s): {t.available_in_backups?.map(b => b.filename).join(', ')}</p>
              </div>
              <button
                className="btn-restore-sm"
                onClick={() => {
                  const filename = t.available_in_backups?.[0]?.filename;
                  if (filename) {
                    setRestoreConfirm({ type: 'tenant', filename, tenantId: t.tenant_id });
                  }
                }}
              >
                <RotateCcw size={12} /> Restore
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );

  return (
    <div className="backup-dashboard">
      {/* Header */}
      <div className="backup-header">
        <div className="backup-header-left">
          <div className="backup-header-icon">
            <HardDrive size={26} />
          </div>
          <div>
            <h2>Backup Management</h2>
            <p>Manage Redis backups, restore tenants, and view audit logs</p>
          </div>
        </div>
        <div className="backup-header-actions">
          <button className="btn-retention" onClick={handleRetention}>
            <Trash2 size={16} /> Enforce Retention
          </button>
          <button className="btn-backup-trigger" onClick={handleTriggerBackup} disabled={triggerLoading}>
            {triggerLoading ? <div className="backup-spinner"></div> : <Database size={16} />}
            {triggerLoading ? 'Creating Backup...' : 'Trigger Backup'}
          </button>
        </div>
      </div>

      {/* Status Banner */}
      {statusMessage && (
        <div className={`backup-status-banner ${statusMessage.type}`}>
          {statusMessage.type === 'success' && <CheckCircle size={18} />}
          {statusMessage.type === 'error' && <XCircle size={18} />}
          {statusMessage.type === 'info' && <Activity size={18} />}
          <span style={{ flex: 1 }}>{statusMessage.text}</span>
          <button onClick={() => setStatusMessage(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="backup-tabs">
        <button className={`backup-tab ${activeView === 'backups' ? 'active' : ''}`} onClick={() => setActiveView('backups')}>
          <Database size={16} /> Backups
        </button>
        <button className={`backup-tab ${activeView === 'tenant-restore' ? 'active' : ''}`} onClick={() => setActiveView('tenant-restore')}>
          <Users size={16} /> Tenant Restore
        </button>
        <button className={`backup-tab ${activeView === 'logs' ? 'active' : ''}`} onClick={() => setActiveView('logs')}>
          <Clock size={16} /> Audit Logs
        </button>
        <button className={`backup-tab ${activeView === 'deleted' ? 'active' : ''}`} onClick={() => setActiveView('deleted')}>
          <Shield size={16} /> Deleted Tenants
        </button>
      </div>

      {/* Content */}
      {activeView === 'backups' && (
        <div className="backup-card">
          <div className="backup-card-header">
            <h3><Database size={18} /> Available Backups</h3>
            <button className="btn-icon-sm" onClick={fetchBackups} title="Refresh"><RefreshCw size={14} /></button>
          </div>
          <div className="backup-card-body">
            {renderBackupsList()}
          </div>
        </div>
      )}

      {activeView === 'tenant-restore' && renderTenantRestore()}
      {activeView === 'logs' && renderLogs()}
      {activeView === 'deleted' && renderDeletedTenants()}

      {/* Preview Modal */}
      {previewData && createPortal(
        <div className="preview-overlay" onClick={() => setPreviewData(null)}>
          <div className="preview-modal" onClick={e => e.stopPropagation()}>
            <div className="preview-modal-header">
              <h3>Backup Preview: {previewData.filename}</h3>
              <button className="preview-close-btn" onClick={() => setPreviewData(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="preview-modal-body">
              <div className="preview-section">
                <h4>Overview</h4>
                <div className="preview-stat-grid">
                  <div className="preview-stat">
                    <label>Total Keys</label>
                    <div className="value">{previewData.total_keys}</div>
                  </div>
                  <div className="preview-stat">
                    <label>Tenants</label>
                    <div className="value">{Object.keys(previewData.tenants || {}).length}</div>
                  </div>
                  <div className="preview-stat">
                    <label>Created</label>
                    <div className="value" style={{ fontSize: '0.8rem' }}>
                      {previewData.metadata?.created_at ? new Date(previewData.metadata.created_at).toLocaleString() : 'N/A'}
                    </div>
                  </div>
                  <div className="preview-stat">
                    <label>Duration</label>
                    <div className="value">{previewData.metadata?.duration_seconds?.toFixed(1) || 'N/A'}s</div>
                  </div>
                </div>
              </div>

              {previewData.tenants && Object.keys(previewData.tenants).length > 0 && (
                <div className="preview-section">
                  <h4>Tenants Breakdown</h4>
                  {Object.entries(previewData.tenants).map(([tid, info]) => (
                    <div key={tid} style={{ padding: '10px 14px', marginBottom: 6, borderRadius: 8, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(148,163,184,0.06)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>tenant:{tid}</span>
                        <span className="badge badge-info">{info.key_count} keys</span>
                      </div>
                      {info.sample_keys?.length > 0 && (
                        <div style={{ marginTop: 6, fontSize: '0.75rem', color: '#64748b', fontFamily: 'monospace' }}>
                          {info.sample_keys.join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {previewData.sample_keys?.length > 0 && (
                <div className="preview-section">
                  <h4>Sample Keys (first 20)</h4>
                  <ul className="preview-key-list">
                    {previewData.sample_keys.map((key, i) => (
                      <li key={i}>{key}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Restore Confirmation Modal */}
      {restoreConfirm && createPortal(
        <div className="restore-confirm-overlay">
          <div className="restore-confirm-modal">
            <div className="warning-icon">
              <AlertTriangle size={28} />
            </div>
            <h3>Confirm {restoreConfirm.type === 'full' ? 'Full System' : 'Tenant'} Restore</h3>
            <p>
              {restoreConfirm.type === 'full'
                ? `This will restore ALL keys from "${restoreConfirm.filename}". This is a dangerous operation.`
                : `This will restore keys for tenant "${restoreConfirm.tenantId}" from "${restoreConfirm.filename}".`
              }
            </p>
            <div className="restore-overwrite-toggle">
              <input
                type="checkbox"
                id="overwrite-toggle"
                checked={restoreOverwrite}
                onChange={() => setRestoreOverwrite(!restoreOverwrite)}
              />
              <label htmlFor="overwrite-toggle">Overwrite existing keys</label>
            </div>
            <div className="restore-confirm-actions">
              <button className="btn-cancel" onClick={() => { setRestoreConfirm(null); setRestoreOverwrite(false); }}>
                Cancel
              </button>
              <button className="btn-confirm-restore" onClick={handleRestore} disabled={restoreLoading}>
                {restoreLoading ? <div className="backup-spinner" style={{ width: 16, height: 16 }}></div> : <RotateCcw size={16} />}
                {restoreLoading ? 'Restoring...' : 'Confirm Restore'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default BackupDashboard;
