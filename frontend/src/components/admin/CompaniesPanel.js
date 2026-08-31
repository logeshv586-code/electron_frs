import React, { useCallback, useEffect, useState } from 'react';
import { Building2, MapPin, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import './CompaniesPanel.css';

const emptyForm = { name: '', company_id: '', address: '' };

const CompaniesPanel = () => {
  const token = useAuthStore((state) => state.token);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const loadCompanies = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE_URL}/api/companies/`, { headers });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Could not load companies.');
      setCompanies(payload.companies || []);
    } catch (requestError) {
      setError(requestError.message || 'Could not load companies.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { loadCompanies(); }, [loadCompanies]);

  const openCreate = () => {
    setForm(emptyForm);
    setDialog({ mode: 'create' });
  };

  const openEdit = (company) => {
    setForm({ name: company.name || '', company_id: company.id || company.company_id || '', address: company.address || '' });
    setDialog({ mode: 'edit', company });
  };

  const closeDialog = () => {
    if (saving) return;
    setDialog(null);
    setForm(emptyForm);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setError('');
    try {
      const isEdit = dialog?.mode === 'edit';
      const companyId = dialog?.company?.id || dialog?.company?.company_id;
      const response = await fetch(isEdit ? `${API_BASE_URL}/api/companies/${companyId}` : `${API_BASE_URL}/api/companies/`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(isEdit
          ? { name: form.name.trim(), address: form.address.trim() }
          : { name: form.name.trim(), company_id: form.company_id.trim() || null, address: form.address.trim() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Could not save company.');
      setDialog(null);
      setForm(emptyForm);
      await loadCompanies();
    } catch (saveError) {
      setError(saveError.message || 'Could not save company.');
    } finally {
      setSaving(false);
    }
  };

  const removeCompany = async (company) => {
    const companyId = company.id || company.company_id;
    if (!window.confirm(`Delete ${company.name || companyId}? Users and biometric data should be reviewed before removing a tenant.`)) return;
    setError('');
    try {
      const response = await fetch(`${API_BASE_URL}/api/companies/${companyId}`, { method: 'DELETE', headers });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Could not delete company.');
      await loadCompanies();
    } catch (deleteError) {
      setError(deleteError.message || 'Could not delete company.');
    }
  };

  return (
    <div className="companies-panel product-surface-page">
      <div className="companies-header product-page-header">
        <div><h2>Companies</h2><p>Manage tenant identities and company-level access boundaries.</p></div>
        <div className="companies-actions">
          <button className="company-secondary" onClick={loadCompanies} disabled={loading}><RefreshCw size={14} /> Refresh</button>
          <button className="company-primary" onClick={openCreate}><Plus size={14} /> Add company</button>
        </div>
      </div>

      {error && <div className="error-message companies-error">{error}</div>}

      <div className="companies-table-shell">
        {loading ? <div className="companies-empty"><div className="loading-spinner" /><span>Loading tenants...</span></div> : companies.length === 0 ? (
          <div className="companies-empty"><Building2 size={28} /><strong>No companies yet</strong><span>Create the first tenant to start isolating cameras, employees and biometric data.</span></div>
        ) : (
          <table className="companies-table">
            <thead><tr><th>Company</th><th>Tenant ID</th><th>Address</th><th>Created</th><th /></tr></thead>
            <tbody>{companies.map((company) => {
              const companyId = company.id || company.company_id || '-';
              return (
                <tr key={companyId}>
                  <td><div className="company-name-cell"><span><Building2 size={15} /></span><strong>{company.name || 'Unnamed company'}</strong></div></td>
                  <td className="company-id-cell">{companyId}</td>
                  <td>{company.address ? <span className="company-address"><MapPin size={12} />{company.address}</span> : '-'}</td>
                  <td>{company.created_at ? new Date(company.created_at).toLocaleDateString() : '-'}</td>
                  <td><div className="company-row-actions"><button title="Edit" onClick={() => openEdit(company)}><Pencil size={13} /></button><button className="danger" title="Delete" onClick={() => removeCompany(company)}><Trash2 size={13} /></button></div></td>
                </tr>
              );
            })}</tbody>
          </table>
        )}
      </div>

      {dialog && (
        <div className="modal-overlay">
          <div className="company-dialog modal-content">
            <div className="company-dialog-header"><div><h3>{dialog.mode === 'edit' ? 'Edit company' : 'Add company'}</h3><p>{dialog.mode === 'edit' ? 'Update tenant display information.' : 'Create an isolated FRS tenant.'}</p></div><button onClick={closeDialog}><X size={16} /></button></div>
            <form onSubmit={submit}>
              <label><span>Company name</span><input autoFocus value={form.name} onChange={(event) => setForm((previous) => ({ ...previous, name: event.target.value }))} placeholder="Acme Industries" required /></label>
              {dialog.mode === 'create' && <label><span>Tenant ID <small>optional</small></span><input value={form.company_id} onChange={(event) => setForm((previous) => ({ ...previous, company_id: event.target.value }))} placeholder="acme-industries" /></label>}
              <label><span>Address</span><textarea value={form.address} onChange={(event) => setForm((previous) => ({ ...previous, address: event.target.value }))} placeholder="Office or site address" /></label>
              <div className="company-dialog-actions"><button type="button" className="company-secondary" onClick={closeDialog}>Cancel</button><button type="submit" className="company-primary" disabled={saving}>{saving ? 'Saving...' : 'Save company'}</button></div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default CompaniesPanel;
