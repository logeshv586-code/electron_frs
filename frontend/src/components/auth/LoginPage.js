import React, { useState } from 'react';
import useAuthStore from '../../store/authStore';
import './LoginPage.css';

const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('SuperAdmin');
  const [isLoading, setIsLoading] = useState(false);
  
  const { login, error, clearError } = useAuthStore();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    clearError();
    
    const result = await login(username, password, role);
    
    if (!result.success) {
      setIsLoading(false);
    }
  };

  const roleOptions = [
    { value: 'SuperAdmin', label: 'Super Admin' },
    { value: 'Admin', label: 'Admin' },
    { value: 'Supervisor', label: 'Supervisor' }
  ];

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-header">
          <h1>FRS Login</h1>
          <p>Face Recognition System</p>
        </div>
        
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter your username"
              required
              disabled={isLoading}
            />
          </div>
          
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              required
              disabled={isLoading}
            />
          </div>
          
          <div className="form-group">
            <label htmlFor="role">Role</label>
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              required
              disabled={isLoading}
            >
              {roleOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          
          {error && (
            <div className="error-message">
              {error}
            </div>
          )}
          
          <button type="submit" className="login-button" disabled={isLoading}>
            {isLoading ? 'Logging in...' : 'Login'}
          </button>
        </form>
        
        <div className="login-footer">
          <p>Default credentials:</p>
          <ul>
            <li>SuperAdmin: eagleai / Eagle@1234</li>
            <li>Admin: admin / admin123</li>
            <li>Supervisor: supervisor / supervisor123</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;