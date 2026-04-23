/* ============================================================
   Compass Health — auth.js
   Authentication state management and routing logic
   ============================================================ */

const Auth = {

  /** Returns true if a JWT access token exists in localStorage */
  isLoggedIn() {
    return !!localStorage.getItem('ch_access_token');
  },

  /** Returns the stored access token string, or null */
  getToken() {
    return localStorage.getItem('ch_access_token');
  },

  /**
   * Persist both tokens to localStorage.
   * @param {string} access  - JWT access token
   * @param {string} refresh - JWT refresh token
   */
  setTokens(access, refresh) {
    localStorage.setItem('ch_access_token', access);
    if (refresh) localStorage.setItem('ch_refresh_token', refresh);
  },

  /** Remove all auth-related keys from localStorage */
  clearTokens() {
    localStorage.removeItem('ch_access_token');
    localStorage.removeItem('ch_refresh_token');
    localStorage.removeItem('ch_has_bmr');
    localStorage.removeItem('ch_is_admin');
  },

  /**
   * Returns true if the user has already completed the BMR wizard.
   * This flag (ch_has_bmr) is set to "1" after a successful BMR save
   * or when login response indicates a profile already exists.
   */
  hasBMRProfile() {
    return localStorage.getItem('ch_has_bmr') === '1';
  },

  /** Cached admin flag from last login/refresh — may be stale until /me runs. */
  isAdmin() {
    return localStorage.getItem('ch_is_admin') === '1';
  },

  setAdmin(flag) {
    localStorage.setItem('ch_is_admin', flag ? '1' : '0');
  },

  /**
   * Main routing logic:
   *  - Not logged in         → auth view
   *  - Logged in, admin      → admin portal (skips BMR wizard entirely)
   *  - Logged in, no BMR     → BMR wizard
   *  - Logged in, has BMR    → main user app
   */
  redirect() {
    if (typeof App === 'undefined') return;
    if (!this.isLoggedIn()) {
      App.showView('auth');
    } else if (this.isAdmin()) {
      App.showView('admin');
    } else if (!this.hasBMRProfile()) {
      App.showView('bmr-wizard');
    } else {
      App.showView('main');
    }
  }
};
