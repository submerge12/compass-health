/* ============================================================
   Compass Health — pages/auth.js
   Login & Registration page
   ============================================================ */

const AuthPage = {
  _activeTab: 'login',

  render() {
    const container = document.getElementById('auth-container');
    if (!container) return;

    container.innerHTML = `
      <div class="auth-card">
        <div class="auth-logo">
          <h1 data-i18n="app.name">指南针健康</h1>
          <p data-i18n="app.tagline">健康生活，从今天开始</p>
        </div>

        <div class="auth-tabs">
          <button class="auth-tab ${this._activeTab === 'login' ? 'active' : ''}"
                  id="tab-login" data-i18n="auth.login">登录</button>
          <button class="auth-tab ${this._activeTab === 'register' ? 'active' : ''}"
                  id="tab-register" data-i18n="auth.register">注册</button>
        </div>

        <!-- Login Panel -->
        <div class="auth-form-panel ${this._activeTab === 'login' ? 'active' : ''}" id="panel-login">
          <form id="form-login" novalidate>
            <div class="form-group">
              <label class="form-label" data-i18n="auth.username">用户名</label>
              <input type="text" id="login-username" class="form-input" autocomplete="username"
                     data-i18n-placeholder="auth.username" required>
              <span class="form-error" id="login-username-err"></span>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="auth.password">密码</label>
              <input type="password" id="login-password" class="form-input" autocomplete="current-password"
                     data-i18n-placeholder="auth.password" required>
              <span class="form-error" id="login-password-err"></span>
            </div>
            <span class="form-error" id="login-global-err" style="display:block;margin-bottom:10px;"></span>
            <button type="submit" class="btn w-full" id="login-btn" data-i18n="auth.login">登录</button>
          </form>
          <div class="auth-switch">
            <span data-i18n="auth.no_account">还没有账号？</span>
            <a id="goto-register" data-i18n="auth.register_now">立即注册</a>
          </div>
        </div>

        <!-- Register Panel -->
        <div class="auth-form-panel ${this._activeTab === 'register' ? 'active' : ''}" id="panel-register">
          <form id="form-register" novalidate>
            <div class="form-group">
              <label class="form-label" data-i18n="auth.username">用户名</label>
              <input type="text" id="reg-username" class="form-input" autocomplete="username"
                     data-i18n-placeholder="auth.username" required>
              <span class="form-error" id="reg-username-err"></span>
            </div>
            <!-- Email field commented out — auto-generated on the server
            <div class="form-group">
              <label class="form-label" data-i18n="auth.email">邮箱</label>
              <input type="email" id="reg-email" class="form-input" autocomplete="email"
                     data-i18n-placeholder="auth.email">
              <span class="form-error" id="reg-email-err"></span>
            </div>
            -->
            <div class="form-group">
              <label class="form-label" data-i18n="auth.password">密码</label>
              <input type="password" id="reg-password" class="form-input" autocomplete="new-password"
                     data-i18n-placeholder="auth.password" required>
              <span class="form-error" id="reg-password-err"></span>
            </div>
            <span class="form-error" id="reg-global-err" style="display:block;margin-bottom:10px;"></span>
            <button type="submit" class="btn w-full" id="register-btn" data-i18n="auth.register">注册</button>
          </form>
          <div class="auth-switch">
            <span data-i18n="auth.has_account">已有账号？</span>
            <a id="goto-login" data-i18n="auth.login_now">立即登录</a>
          </div>
        </div>
      </div>
    `;

    I18n.apply();
    this._bindEvents();
  },

  _bindEvents() {
    // Tab switching
    const tabLogin    = document.getElementById('tab-login');
    const tabRegister = document.getElementById('tab-register');

    tabLogin?.addEventListener('click', () => this.showLogin());
    tabRegister?.addEventListener('click', () => this.showRegister());

    document.getElementById('goto-register')?.addEventListener('click', () => this.showRegister());
    document.getElementById('goto-login')?.addEventListener('click', () => this.showLogin());

    // Login form
    document.getElementById('form-login')?.addEventListener('submit', e => {
      e.preventDefault();
      this._handleLogin();
    });

    // Register form
    document.getElementById('form-register')?.addEventListener('submit', e => {
      e.preventDefault();
      this._handleRegister();
    });
  },

  showLogin() {
    this._activeTab = 'login';
    document.getElementById('tab-login')?.classList.add('active');
    document.getElementById('tab-register')?.classList.remove('active');
    document.getElementById('panel-login')?.classList.add('active');
    document.getElementById('panel-register')?.classList.remove('active');
  },

  showRegister() {
    this._activeTab = 'register';
    document.getElementById('tab-register')?.classList.add('active');
    document.getElementById('tab-login')?.classList.remove('active');
    document.getElementById('panel-register')?.classList.add('active');
    document.getElementById('panel-login')?.classList.remove('active');
  },

  /* ── Validation helpers ── */
  _showErr(id, msg) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.classList.add('visible');
  },

  _clearErr(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = '';
    el.classList.remove('visible');
  },

  _clearAllErrors(prefix) {
    ['username', 'email', 'password', 'global'].forEach(f => {
      this._clearErr(`${prefix}-${f}-err`);
    });
    this._clearErr(`${prefix}-global-err`);
  },

  /* ── Login handler ── */
  async _handleLogin() {
    this._clearAllErrors('login');

    const username = document.getElementById('login-username')?.value.trim();
    const password = document.getElementById('login-password')?.value;

    let valid = true;
    if (!username) {
      this._showErr('login-username-err', I18n.t('auth.username') + (I18n.lang === 'zh' ? '不能为空' : ' is required'));
      valid = false;
    }
    if (!password) {
      this._showErr('login-password-err', I18n.t('auth.password') + (I18n.lang === 'zh' ? '不能为空' : ' is required'));
      valid = false;
    }
    if (!valid) return;

    const btn = document.getElementById('login-btn');
    btn.disabled = true;
    btn.classList.add('btn-loading');
    btn.textContent = I18n.t('common.loading');

    try {
      const data = await API.login(username, password);

      // Support various token response shapes
      const accessToken  = data.access_token  || data.accessToken  || data.token;
      const refreshToken = data.refresh_token || data.refreshToken || '';

      if (!accessToken) throw new Error('Invalid response from server');

      Auth.setTokens(accessToken, refreshToken);

      // Determine if user already has BMR profile
      const hasBMR = !!(data.has_bmr_profile || data.hasBMRProfile || data.bmr_complete);
      localStorage.setItem('ch_has_bmr', hasBMR ? '1' : '0');
      Auth.setAdmin(!!data.is_admin);

      Auth.redirect();
    } catch (err) {
      this._showErr('login-global-err', err.message || I18n.t('common.error'));
    } finally {
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      btn.textContent = I18n.t('auth.login');
    }
  },

  /* ── Register handler ── */
  async _handleRegister() {
    this._clearAllErrors('reg');

    const username      = document.getElementById('reg-username')?.value.trim();
    const password      = document.getElementById('reg-password')?.value;
    const isZh = I18n.lang === 'zh';

    let valid = true;

    if (!username || username.length < 3) {
      this._showErr('reg-username-err',
        isZh ? '用户名至少3个字符' : 'Username must be at least 3 characters');
      valid = false;
    }

    if (!password || password.length < 6) {
      this._showErr('reg-password-err',
        isZh ? '密码至少6个字符' : 'Password must be at least 6 characters');
      valid = false;
    }

    if (!valid) return;

    const btn = document.getElementById('register-btn');
    btn.disabled = true;
    btn.classList.add('btn-loading');
    btn.textContent = I18n.t('common.loading');

    try {
      const data = await API.register(username, password);

      const accessToken  = data.access_token  || data.accessToken  || data.token;
      const refreshToken = data.refresh_token || data.refreshToken || '';

      if (!accessToken) {
        // Registration succeeded but no auto-login — show login tab
        App.showToast(I18n.lang === 'zh' ? '注册成功，请登录' : 'Registered! Please log in.', 'success');
        this.showLogin();
        return;
      }

      Auth.setTokens(accessToken, refreshToken);
      localStorage.setItem('ch_has_bmr', '0'); // new users never have BMR profile yet
      Auth.setAdmin(!!data.is_admin);          // first-ever registration auto-admins
      Auth.redirect();
    } catch (err) {
      this._showErr('reg-global-err', err.message || I18n.t('common.error'));
    } finally {
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      btn.textContent = I18n.t('auth.register');
    }
  }
};
