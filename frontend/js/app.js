/* ============================================================
   Compass Health — app.js
   Main application controller
   ============================================================ */

const App = {
  /** Currently active page name */
  _currentPage: 'dashboard',

  /** Current active navigation key for header state */
  _currentNavKey: 'dashboard',

  /** Map of page name → page module */
  _pages: {},

  /** Currently logged-in user object (populated after login) */
  _user: null,

  /* ────────────────────────────────────────────────────────
     Initialisation — called on DOMContentLoaded
     ──────────────────────────────────────────────────────── */
  init() {
    // Register user-facing page modules. The admin portal lives in its own
    // view (#view-admin) and is handled by AdminPortal, not this registry.
    this._pages = {
      dashboard: typeof DashboardPage !== 'undefined' ? DashboardPage : null,
        voice: typeof VoicePage !== 'undefined' ? VoicePage : null,
      water:     typeof WaterPage     !== 'undefined' ? WaterPage     : null,
      exercise:  typeof ExercisePage  !== 'undefined' ? ExercisePage  : null,
      diet:      typeof DietPage      !== 'undefined' ? DietPage      : null,
      plan:      typeof MealEnginePage !== 'undefined' ? MealEnginePage : null,
      condition: typeof ConditionPage !== 'undefined' ? ConditionPage : null,
      stats:     typeof StatsPage     !== 'undefined' ? StatsPage     : null,
      settings:  typeof SettingsPage  !== 'undefined' ? SettingsPage  : null,
    };

    // Apply i18n to initial DOM
    I18n.apply();

    // Set date in nav
    this._setNavDate();

    // Bind app navigation links via delegation so header and homepage cards
    // can share the same routing contract.
    const mainView = document.getElementById('view-main');
    if (mainView) {
      mainView.addEventListener('click', e => {
        const trigger = e.target.closest('[data-app-nav][data-page]');
        if (!trigger || !mainView.contains(trigger)) return;
        e.preventDefault();
        this.navigate(trigger.getAttribute('data-page'), {
          navKey: trigger.getAttribute('data-nav-key') || undefined,
          planTab: trigger.getAttribute('data-plan-tab') || undefined,
          dietTab: trigger.getAttribute('data-diet-tab') || undefined,
        });
      });
    }

    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', async () => {
        await API.logout();
        Auth.clearTokens();
        this.showView('auth');
        AuthPage.render();
      });
    }

    // Language toggle
    const langToggle = document.getElementById('lang-toggle');
    if (langToggle) {
      langToggle.addEventListener('click', () => {
        const next = I18n.lang === 'zh' ? 'en' : 'zh';
        I18n.setLang(next);
      });
    }

    // Re-render current page on language change
    document.addEventListener('langchange', () => {
      this._setNavDate();
      if (this._user) this.updateUserInfo(this._user);
      // Re-render whichever view is currently active
      const adminView = document.getElementById('view-admin');
      if (adminView && !adminView.classList.contains('hidden') && typeof AdminPortal !== 'undefined') {
        AdminPortal.navigate(AdminPortal._currentPage || 'dashboard');
        return;
      }
      const page = this._pages[this._currentPage];
      if (page && typeof page.render === 'function') {
        page.render();
      }
    });

    // Modal overlay click to close
    const modalOverlay = document.getElementById('modal-overlay');
    if (modalOverlay) {
      modalOverlay.addEventListener('click', e => {
        if (e.target === modalOverlay) this.closeModal();
      });
    }

    // Route on load
    Auth.redirect();
  },

  /* ────────────────────────────────────────────────────────
     View management
     ──────────────────────────────────────────────────────── */

  /**
   * Switch between top-level views: 'auth' | 'bmr-wizard' | 'preferences' | 'main' | 'admin'
   */
  showView(name) {
    const views = {
      'auth':        'view-auth',
      'bmr-wizard':  'view-bmr',
      'preferences': 'view-preferences',
      'main':        'view-main',
      'admin':       'view-admin'
    };

    // Hide all views
    Object.values(views).forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });

    // Show target view
    const targetId = views[name];
    if (targetId) {
      const el = document.getElementById(targetId);
      if (el) el.classList.remove('hidden');
    }

    // Trigger rendering for the view
    if (name === 'auth') {
      AuthPage.render();
      I18n.apply();
    } else if (name === 'bmr-wizard') {
      BMRPage.render();
      I18n.apply();
    } else if (name === 'preferences') {
      PreferencesPage.render();
      I18n.apply();
    } else if (name === 'main') {
      // Load user info then default page
      this._initMainApp();
    } else if (name === 'admin') {
      if (typeof AdminPortal !== 'undefined') AdminPortal.init();
      I18n.apply();
    }
  },

  /** Load user info and render the default page */
  async _initMainApp() {
    try {
      const user = await API.getMe();
      // Defense-in-depth: if somehow an admin landed in the user view,
      // bounce them back to the admin portal so the separation holds.
      if (user.is_admin) {
        Auth.setAdmin(true);
        this.showView('admin');
        return;
      }
      Auth.setAdmin(false);
      this.updateUserInfo(user);
    } catch (err) {
      console.warn('Could not fetch user info:', err.message);
    }
    this.navigate(this._currentPage);
  },

  /* ────────────────────────────────────────────────────────
     Page navigation within main app
     ──────────────────────────────────────────────────────── */

  /**
   * Navigate to a named page within the main app.
   */
  navigate(page, options = {}) {
    this._currentPage = page;
    this._currentNavKey = this._resolveNavKey(page, options);
    this._applyPageOptions(page, options);
    this.loadPage(page);
  },

  /**
   * Activate a page div, deactivate others, update nav, call render().
   */
  loadPage(page) {
    // Update page divs
    document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    // Update nav active state
    document.querySelectorAll('[data-nav-link][data-page]').forEach(link => {
      const navKey = link.getAttribute('data-nav-key') || link.getAttribute('data-page');
      link.classList.toggle('active', navKey === this._currentNavKey);
    });

    // Call the page's render function
    const module = this._pages[page];
    if (module && typeof module.render === 'function') {
      module.render();
    }

    // Re-apply i18n
    I18n.apply();
  },

  /* ────────────────────────────────────────────────────────
     Toast notifications
     ──────────────────────────────────────────────────────── */

  /**
   * Show a toast notification.
   * @param {string} msg   - Message text
   * @param {'success'|'error'|'info'} type
   */
  showToast(msg, type = 'info') {
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = icons[type] || icons.info;

    const text = document.createElement('span');
    text.textContent = msg == null ? '' : String(msg);

    toast.append(icon, text);

    container.appendChild(toast);

    // Dismiss on click
    toast.addEventListener('click', () => this._dismissToast(toast));

    // Auto-dismiss after 3s
    setTimeout(() => this._dismissToast(toast), 3000);
  },

  _dismissToast(toast) {
    if (!toast.parentNode) return;
    toast.classList.add('out');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  },

  /* ────────────────────────────────────────────────────────
     Modal
     ──────────────────────────────────────────────────────── */

  /**
   * Open the generic modal.
   * @param {string} title   - Modal heading
   * @param {string} content - HTML content for the body
   * @param {string} footer  - HTML content for the footer (buttons etc.)
   */
  openModal(title, content, footer = '') {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-content').innerHTML = content;
    document.getElementById('modal-footer').innerHTML = footer;
    document.getElementById('modal-overlay').classList.remove('hidden');
  },

  closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.getElementById('modal-title').textContent = '';
    document.getElementById('modal-content').innerHTML = '';
    document.getElementById('modal-footer').innerHTML = '';
  },

  /* ────────────────────────────────────────────────────────
     User info in nav
     ──────────────────────────────────────────────────────── */

  /**
   * Update the nav user display.
   * @param {object} user - User object from API.getMe()
   */
  updateUserInfo(user) {
    this._user = user;

    const usernameEl = document.getElementById('nav-username');
    if (usernameEl) usernameEl.textContent = user.username || user.email || '';

    const badgeEl = document.getElementById('nav-membership-badge');
    if (badgeEl) {
      const level = user.membership_level || 'free';
      badgeEl.className = `badge badge-${level}`;
      badgeEl.textContent = I18n.t(`membership.${level}`);
    }
  },

  _resolveNavKey(page, options = {}) {
    if (options.navKey) return options.navKey;
    if (page === 'plan') {
      return options.planTab === 'procurement' ? 'plan-procurement' : 'plan-meal';
    }
    if (page === 'diet') {
      return options.dietTab === 'recipes' ? 'diet-recipes' : 'diet';
    }
    return page;
  },

  _applyPageOptions(page, options = {}) {
    if (page === 'plan' && typeof MealEnginePage !== 'undefined' && options.planTab) {
      MealEnginePage._activeTab = options.planTab;
    }
    if (page === 'diet' && typeof DietPage !== 'undefined' && options.dietTab) {
      DietPage._pendingTab = options.dietTab;
    }
  },

  /* ────────────────────────────────────────────────────────
     Nav date display
     ──────────────────────────────────────────────────────── */
  _setNavDate() {
    const now = new Date();
    const locale = I18n.lang === 'zh' ? 'zh-CN' : 'en-US';

    const weekdayEl = document.getElementById('nav-weekday');
    const datenumEl = document.getElementById('nav-datenum');
    const monthyearEl = document.getElementById('nav-monthyear');

    if (weekdayEl) {
      weekdayEl.textContent = now.toLocaleDateString(locale, { weekday: 'long' });
    }
    if (datenumEl) {
      datenumEl.textContent = now.getDate();
    }
    if (monthyearEl) {
      monthyearEl.textContent = now.toLocaleDateString(locale, { month: 'long', year: 'numeric' });
    }
  }
};

/* ── Bootstrap ── */
document.addEventListener('DOMContentLoaded', () => App.init());
