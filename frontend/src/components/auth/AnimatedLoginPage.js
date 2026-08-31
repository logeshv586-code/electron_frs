import React, { useMemo, useState } from 'react';
import {
  ArrowLeft,
  Camera,
  CheckCircle2,
  Clock3,
  Eye,
  EyeOff,
  KeyRound,
  LockKeyhole,
  ScanFace,
  ShieldCheck,
  UserRound,
  Users,
} from 'lucide-react';
import useAuthStore from '../../store/authStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import './AnimatedLoginPage.css';

const AnimatedLoginPage = () => {
  const { login, error, clearError } = useAuthStore();
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [inlineError, setInlineError] = useState('');
  const [notice, setNotice] = useState('');

  const [resetUsername, setResetUsername] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);

  const visibleError = inlineError || error;

  const heading = useMemo(() => {
    if (mode === 'request') return { title: 'Reset your password', subtitle: 'Request a one-time token for your account.' };
    if (mode === 'reset') return { title: 'Create a new password', subtitle: 'Enter the one-time token and choose a new password.' };
    if (mode === 'success') return { title: 'Password updated', subtitle: 'Your active sessions were revoked for security.' };
    return { title: 'Welcome back', subtitle: 'Sign in to manage attendance, cameras and recognition.' };
  }, [mode]);

  const resetMessages = () => {
    setInlineError('');
    setNotice('');
    clearError();
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    resetMessages();
    if (!username.trim() || !password) {
      setInlineError('Enter your username and password.');
      return;
    }

    setIsLoading(true);
    const result = await login(username.trim(), password, null);
    setIsLoading(false);
    if (!result.success) {
      setInlineError(result.error || 'Sign in failed. Check your credentials and try again.');
    }
  };

  const handleRequestToken = async (event) => {
    event.preventDefault();
    resetMessages();
    const targetUsername = resetUsername.trim() || username.trim();
    if (!targetUsername) {
      setInlineError('Enter the username you use to sign in.');
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: targetUsername }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not request a reset token.');
      setResetUsername(targetUsername);
      if (data.dev_token) setResetToken(data.dev_token);
      setNotice(data.message || 'If the account exists, a reset token has been sent.');
      setMode('reset');
    } catch (requestError) {
      setInlineError(requestError.message || 'Could not contact the authentication service.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (event) => {
    event.preventDefault();
    resetMessages();
    if (!resetUsername.trim() || !resetToken.trim()) {
      setInlineError('Username and one-time token are required.');
      return;
    }
    if (newPassword.length < 8) {
      setInlineError('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setInlineError('The new passwords do not match.');
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: resetUsername.trim(),
          token: resetToken.trim(),
          new_password: newPassword,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Password reset failed.');
      setPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setResetToken('');
      setNotice(data.message || 'Password reset successfully.');
      setMode('success');
    } catch (resetError) {
      setInlineError(resetError.message || 'Invalid or expired reset token.');
    } finally {
      setIsLoading(false);
    }
  };

  const goToLogin = () => {
    resetMessages();
    setMode('login');
  };

  const renderPasswordButton = (visible, onToggle, label) => (
    <button type="button" className="auth-visibility" onClick={onToggle} aria-label={label} tabIndex={-1}>
      {visible ? <EyeOff size={16} /> : <Eye size={16} />}
    </button>
  );

  return (
    <div className="product-login-page">
      <div className="login-window">
        <section className="login-form-pane">
          <div className="login-brand">
            <span className="login-brand-mark"><ScanFace size={20} /></span>
            <div>
              <strong>Face Recognition</strong>
              <span>Attendance System</span>
            </div>
          </div>

          <div className="login-form-wrap">
            {mode !== 'login' && mode !== 'success' && (
              <button type="button" className="auth-back" onClick={goToLogin}><ArrowLeft size={15} /> Back to sign in</button>
            )}

            <div className="login-heading">
              <h1>{heading.title}</h1>
              <p>{heading.subtitle}</p>
            </div>

            {visibleError && <div className="auth-inline-message error"><span>!</span>{visibleError}</div>}
            {notice && <div className="auth-inline-message success"><CheckCircle2 size={16} />{notice}</div>}

            {mode === 'login' && (
              <form className="product-login-form" onSubmit={handleLogin}>
                <label className="auth-field">
                  <span>Username</span>
                  <div className="auth-input-wrap">
                    <UserRound size={16} />
                    <input
                      autoFocus
                      autoComplete="username"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      placeholder="Enter username"
                      disabled={isLoading}
                    />
                  </div>
                </label>

                <label className="auth-field">
                  <span>Password</span>
                  <div className="auth-input-wrap">
                    <LockKeyhole size={16} />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Enter password"
                      disabled={isLoading}
                    />
                    {renderPasswordButton(showPassword, () => setShowPassword((value) => !value), 'Toggle password visibility')}
                  </div>
                </label>

                <div className="auth-form-meta">
                  <span className="role-detection"><ShieldCheck size={14} /> Role detected automatically</span>
                  <button type="button" className="auth-link" onClick={() => { resetMessages(); setResetUsername(username); setMode('request'); }}>Forgot password?</button>
                </div>

                <button className="auth-primary-button" type="submit" disabled={isLoading}>
                  {isLoading ? <><span className="auth-spinner" /> Signing in...</> : 'Sign in'}
                </button>
              </form>
            )}

            {mode === 'request' && (
              <form className="product-login-form" onSubmit={handleRequestToken}>
                <label className="auth-field">
                  <span>Username</span>
                  <div className="auth-input-wrap">
                    <UserRound size={16} />
                    <input autoFocus value={resetUsername} onChange={(event) => setResetUsername(event.target.value)} placeholder="Enter username" />
                  </div>
                </label>
                <div className="reset-note"><Clock3 size={15} /><span>The token is valid for 15 minutes and can be used once.</span></div>
                <button className="auth-primary-button" type="submit" disabled={isLoading}>{isLoading ? 'Requesting token...' : 'Request one-time token'}</button>
              </form>
            )}

            {mode === 'reset' && (
              <form className="product-login-form" onSubmit={handleResetPassword}>
                <label className="auth-field">
                  <span>Username</span>
                  <div className="auth-input-wrap"><UserRound size={16} /><input value={resetUsername} onChange={(event) => setResetUsername(event.target.value)} /></div>
                </label>
                <label className="auth-field">
                  <span>One-time token</span>
                  <div className="auth-input-wrap"><KeyRound size={16} /><input autoFocus value={resetToken} onChange={(event) => setResetToken(event.target.value)} placeholder="Enter token" /></div>
                </label>
                <label className="auth-field">
                  <span>New password</span>
                  <div className="auth-input-wrap">
                    <LockKeyhole size={16} />
                    <input type={showNewPassword ? 'text' : 'password'} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="Minimum 8 characters" />
                    {renderPasswordButton(showNewPassword, () => setShowNewPassword((value) => !value), 'Toggle new password visibility')}
                  </div>
                </label>
                <label className="auth-field">
                  <span>Confirm password</span>
                  <div className="auth-input-wrap"><LockKeyhole size={16} /><input type={showNewPassword ? 'text' : 'password'} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Repeat new password" /></div>
                </label>
                <button className="auth-primary-button" type="submit" disabled={isLoading}>{isLoading ? 'Updating password...' : 'Reset password'}</button>
              </form>
            )}

            {mode === 'success' && (
              <div className="reset-success-panel">
                <span className="reset-success-icon"><CheckCircle2 size={27} /></span>
                <p>Your password is ready. Sign in again using the new credentials.</p>
                <button className="auth-primary-button" type="button" onClick={goToLogin}>Return to sign in</button>
              </div>
            )}
          </div>

          <div className="login-footer">Secure biometric attendance • Tenant-isolated access</div>
        </section>

        <aside className="login-product-pane" aria-label="Product information">
          <div className="product-visual">
            <div className="visual-grid" />
            <div className="face-focus-frame">
              <span className="focus-corner top-left" /><span className="focus-corner top-right" />
              <span className="focus-corner bottom-left" /><span className="focus-corner bottom-right" />
              <div className="face-focus-icon"><ScanFace size={82} strokeWidth={1.05} /></div>
              <div className="focus-status"><span /> Identity verification ready</div>
            </div>
          </div>

          <div className="product-copy">
            <h2>Attendance with recognition evidence you can trust.</h2>
            <p>Designed for multi-camera, multi-tenant attendance with conservative identity decisions and first-in / last-out records.</p>
            <div className="product-capabilities">
              <div><Camera size={16} /><span><strong>Multi-camera</strong><small>Entry, exit and reference roles</small></span></div>
              <div><Users size={16} /><span><strong>Crowd aware</strong><small>Multiple faces tracked independently</small></span></div>
              <div><ShieldCheck size={16} /><span><strong>Tenant isolated</strong><small>Protected biometric access</small></span></div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
};

export default AnimatedLoginPage;
