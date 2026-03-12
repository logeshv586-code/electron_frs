import React, { useState, useEffect } from 'react';
import useAuthStore from '../../store/authStore';
import './AnimatedLoginPage.css';
import securityCoinIcon from '../../icon/securitycoin.png';

const AnimatedLoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [forgotUsername, setForgotUsername] = useState('');
  const [forgotMessage, setForgotMessage] = useState('');

  const { login, error, clearError, logout, setAuthenticated } = useAuthStore();

  useEffect(() => {
    // Initialize animations
    updateCoinAppearance();
  }, []);

  useEffect(() => {
    updateCoinAppearance();
  }, [role]);

  const updateCoinAppearance = () => {
    const coin = document.getElementById('animatedCoin');
    const coinTexts = document.querySelectorAll('.coin-text');

    if (coin) {
      // Preserve the auth-coin class but reset other classes
      coin.className = 'auth-coin';

      let roleText = '';
      if (role) {
        coin.classList.add(`coin-${role}`);
      }

      // Update all text elements (front and back)
      coinTexts.forEach(el => {
        el.textContent = roleText;
      });
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    // Validation (Role is now optional for SuperAdmin/Auto-detection)
    if (!username.trim() || !password.trim()) {
      alert('Please enter username and password');
      return;
    }

    setIsLoading(true);
    clearError();

    // Start animation sequence
    startLoginAnimation();

    // Add a minimum delay for the inserting animation
    const minAnimationTime = new Promise(resolve => setTimeout(resolve, 1500));

    try {
      // Pass null or empty string if no role is selected, the backend will auto-discover
      const loginPromise = login(username, password, role || null, true);
      const [result] = await Promise.all([loginPromise, minAnimationTime]);

      if (result.success) {
        // Success animation
        completeLoginAnimation();

        // Wait for success animation before navigating
        setTimeout(() => {
          setIsLoading(false);
          setAuthenticated(true);
        }, 2000);
      } else {
        // Failed animation
        setTimeout(() => {
          failedLoginAnimation();
        }, 1000);

        setTimeout(() => {
          setIsLoading(false);
          resetAnimation();
        }, 3000);

        // Show specific error message from backend
        if (result.error) {
          alert(`Authentication failed: ${result.error}`);
        } else {
          alert('Authentication failed. Please check your credentials and try again.');
        }
      }
    } catch (error) {
      // Network/server error
      setTimeout(() => {
        failedLoginAnimation();
      }, 1000);

      setTimeout(() => {
        setIsLoading(false);
        resetAnimation();
      }, 3000);

      alert('Unable to connect to authentication server. Please try again later.');
    }
  };

  const startLoginAnimation = () => {
    const coinBank = document.getElementById('coinBank');
    const animatedCoin = document.getElementById('animatedCoin');

    if (coinBank) {
      coinBank.classList.add('login-active');
      coinBank.style.transform = 'translate3d(-50%, -50%, 0) rotateX(0deg) rotateY(0deg) scale(1.1)';
    }

    if (animatedCoin) {
      animatedCoin.classList.add('inserting');
    }
  };

  const completeLoginAnimation = () => {
    const cubeFaces = document.querySelectorAll('.cube-face');
    const successMessage = document.getElementById('successMessage');
    const animatedCoin = document.getElementById('animatedCoin');

    // Add success glow to cube
    cubeFaces.forEach(face => {
      face.classList.add('success-glow');
    });

    // Add success state to coin
    if (animatedCoin) {
      animatedCoin.classList.add('success');
    }

    // Show success message
    if (successMessage) {
      successMessage.textContent = '✓ AUTHENTICATION SUCCESSFUL';
      successMessage.classList.add('show');
    }
  };

  const failedLoginAnimation = () => {
    const animatedCoin = document.getElementById('animatedCoin');
    const successMessage = document.getElementById('successMessage');

    // Add failed state to coin
    if (animatedCoin) {
      animatedCoin.classList.add('failed');
    }

    // Show failed message
    if (successMessage) {
      successMessage.textContent = '✗ AUTHENTICATION FAILED';
      successMessage.style.background = 'linear-gradient(90deg, var(--error-color), #cc0000)';
      successMessage.classList.add('show');
    }
  };

  const resetAnimation = () => {
    const coinBank = document.getElementById('coinBank');
    const animatedCoin = document.getElementById('animatedCoin');
    const cubeFaces = document.querySelectorAll('.cube-face');
    const successMessage = document.getElementById('successMessage');

    if (coinBank) {
      coinBank.classList.remove('login-active');
      coinBank.style.transform = '';
    }

    if (animatedCoin) {
      animatedCoin.classList.remove('inserting', 'success', 'failed');
    }

    cubeFaces.forEach(face => {
      face.classList.remove('success-glow');
    });

    if (successMessage) {
      successMessage.classList.remove('show');
      successMessage.style.background = '';
    }
  };

  const togglePassword = () => {
    setShowPassword(!showPassword);
  };

  return (
    <div className={`animated-login-container ${isExiting ? 'exiting' : ''}`}>
      <video className="login-background-video" autoPlay loop muted playsInline>
        <source src={process.env.PUBLIC_URL + '/assets/login-bg.mov'} type="video/quicktime" />
        <source src={process.env.PUBLIC_URL + '/assets/login-bg.mov'} type="video/mp4" />
      </video>
      <div className="main-container">
        <div className="glass-wrapper">
          {/* Left Side - Login Form */}
          <div className="login-section">
            <form onSubmit={handleSubmit} id="loginForm" className="login-form">
              <div className="form-group">
                <label htmlFor="role" className="form-label">ACCESS LEVEL</label>
                <select
                  id="role"
                  name="role"
                  className="form-input"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="" disabled hidden>SELECT ROLE</option>
                  <option value="Admin">ADMIN</option>
                  <option value="Supervisor">SUPERVISOR</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="username" className="form-label">USERNAME</label>
                <div className="input-with-icon">
                  <input
                    type="text"
                    id="username"
                    name="username"
                    className="form-input"
                    placeholder="ENTER USERNAME"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                    disabled={isLoading}
                  />
                  <div className="input-icon">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                      <circle cx="12" cy="7" r="4"></circle>
                    </svg>
                  </div>
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="password" className="form-label">PASSWORD</label>
                <div className="password-wrapper input-with-icon">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    id="password"
                    name="password"
                    className="form-input"
                    placeholder="ENTER PASSWORD"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    disabled={isLoading}
                  />
                  <button
                    type="button"
                    className="toggle-password"
                    onClick={togglePassword}
                    disabled={isLoading}
                  >
                    {showPassword ? (
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                        <line x1="1" y1="1" x2="23" y2="23"></line>
                      </svg>
                    ) : (
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              {error && (
                <div className="error-message">
                  {error}
                </div>
              )}

              <div className="forgot-password-link">
                <button 
                  type="button" 
                  className="link-btn"
                  onClick={() => {
                    setIsForgotPassword(true);
                    setForgotUsername(username);
                    setForgotMessage('');
                  }}
                >
                  FORGOT PASSWORD?
                </button>
              </div>

              <div className="form-group submit-group">
                <button
                  type="submit"
                  className="login-button"
                  id="loginButton"
                  disabled={isLoading}
                >
                  {isLoading ? 'AUTHENTICATING...' : 'AUTHENTICATE'}
                </button>
              </div>

              <div className="form-footer">
                <p className="login-help-text">SECURE FACE RECOGNITION ACCESS</p>
              </div>
            </form>

            {/* Forgot Password Overlay */}
            {isForgotPassword && (
              <div className="forgot-password-overlay">
                <div className="forgot-password-card">
                  <h3>RESET PASSWORD</h3>
                  <p>ENTER YOUR USERNAME TO RECEIVE RESET INSTRUCTIONS</p>
                  <div className="form-group">
                    <input
                      type="text"
                      className="form-input"
                      placeholder="USERNAME"
                      value={forgotUsername}
                      onChange={(e) => setForgotUsername(e.target.value)}
                    />
                  </div>
                  {forgotMessage && <div className="forgot-status">{forgotMessage}</div>}
                  <div className="modal-actions">
                    <button 
                      className="login-button secondary"
                      onClick={() => setIsForgotPassword(false)}
                    >
                      CANCEL
                    </button>
                    <button 
                      className="login-button"
                      onClick={async () => {
                        if (!forgotUsername.trim()) {
                          alert('Please enter your username');
                          return;
                        }
                        try {
                          const response = await fetch('/api/auth/forgot-password', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ username: forgotUsername })
                          });
                          const data = await response.json();
                          setForgotMessage(data.message);
                        } catch (err) {
                          setForgotMessage('NETWORK ERROR. PLEASE TRY AGAIN.');
                        }
                      }}
                    >
                      SEND RESET LINK
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right Side - Visual/Animation */}
          <div className="visual-section">
            <div className="visual-content">
              {/* Face Recognition Authentication Coin */}
              <div className="auth-coin" id="animatedCoin">
                <div className="coin-face front">
                  <img src={securityCoinIcon} className="auth-coin-icon-img" alt="Security" />
                  <div className="coin-text"></div>
                </div>
                <div className="coin-face back">
                  <img src={securityCoinIcon} className="auth-coin-icon-img" alt="Security" />
                  <div className="coin-text"></div>
                </div>
              </div>

              {/* Professional Authentication Cube */}
              <div className="scene-container">
                <div className="face-recognition-cube" id="coinBank">
                  <div className="cube-face front"></div>
                  <div className="cube-face back"></div>
                  <div className="cube-face right"></div>
                  <div className="cube-face left"></div>
                  <div className="cube-face top"></div>
                  <div className="cube-face bottom"></div>
                </div>

                {/* Authentication Status Message */}
                <div className="success-message" id="successMessage">
                  ✓ READY FOR AUTHENTICATION
                </div>
              </div>

              <div className="particles">
                <div className="particle"></div>
                <div className="particle"></div>
                <div className="particle"></div>
                <div className="particle"></div>
                <div className="particle"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AnimatedLoginPage;
