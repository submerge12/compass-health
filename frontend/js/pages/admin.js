/* ============================================================
   Compass Health — pages/admin.js
   Admin portal: dashboard, reports, recipes, users.
   Runs inside the dedicated #view-admin shell — no user-side
   features (water/diet/exercise/etc.) are accessible from here.
   ============================================================ */

const AdminPortal = {

  _currentPage: 'dashboard',
  _currentAdmin: null,
  _reportsById: new Map(),
  _usersById: new Map(),

  /* ── Bootstrap ───────────────────────────────────────────────── */

  async init() {
    try {
      const me = await API.getMe();
      if (!me.is_admin) {
        // Non-admin reached the admin view somehow — bounce them out.
        Auth.setAdmin(false);
        localStorage.setItem('ch_has_bmr', me.has_bmr_profile ? '1' : '0');
        App.showView(me.has_bmr_profile ? 'main' : 'bmr-wizard');
        return;
      }
      this._currentAdmin = me;
      const usernameEl = document.getElementById('admin-username');
      if (usernameEl) usernameEl.textContent = me.username || me.email || '';
    } catch {
      App.showView('auth');
      return;
    }

    this._bindChrome();
    this.navigate(this._currentPage);
  },

  _bindChrome() {
    document.querySelectorAll('#admin-nav nav a[data-admin-page]').forEach(link => {
      // Rebinding on every init is safe — cloneNode clears stale listeners.
      const fresh = link.cloneNode(true);
      link.parentNode.replaceChild(fresh, link);
      fresh.addEventListener('click', e => {
        e.preventDefault();
        this.navigate(fresh.getAttribute('data-admin-page'));
      });
    });

    const logoutBtn = document.getElementById('admin-logout-btn');
    if (logoutBtn) {
      const fresh = logoutBtn.cloneNode(true);
      logoutBtn.parentNode.replaceChild(fresh, logoutBtn);
      fresh.addEventListener('click', async () => {
        await API.logout();
        Auth.clearTokens();
        App.showView('auth');
      });
    }

    const langBtn = document.getElementById('admin-lang-toggle');
    if (langBtn) {
      const fresh = langBtn.cloneNode(true);
      langBtn.parentNode.replaceChild(fresh, langBtn);
      fresh.addEventListener('click', () => {
        I18n.setLang(I18n.lang === 'zh' ? 'en' : 'zh');
      });
    }
  },

  navigate(page) {
    this._currentPage = page;

    document.querySelectorAll('#view-admin .page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`admin-page-${page}`);
    if (target) target.classList.add('active');

    document.querySelectorAll('#admin-nav nav a[data-admin-page]').forEach(a =>
      a.classList.toggle('active', a.getAttribute('data-admin-page') === page)
    );

    if (page === 'dashboard') this._renderDashboard();
    else if (page === 'reports') this._renderReports();
    else if (page === 'recipes') this._renderRecipes();
    else if (page === 'users') this._renderUsers();
    else if (page === 'ops') this._renderOps();

    I18n.apply();
  },

  /* ── Dashboard ───────────────────────────────────────────────── */

  async _renderDashboard() {
    const el = document.getElementById('admin-page-dashboard');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('admin.dashboard_title')}</h2></div>
      </div>
      <div id="admin-stats-wrap">
        <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
      </div>`;

    try {
      const s = await API.adminGetStats();
      document.getElementById('admin-stats-wrap').innerHTML = `
        <div class="admin-stat-grid">
          ${this._statCard(t('admin.stat_total_users'), s.total_users,
             `${s.active_users} ${t('admin.user_active').toLowerCase()} · ${s.admin_users} ${t('admin.role_badge').toLowerCase()}`)}
          ${this._statCard(t('admin.stat_total_recipes'), s.total_recipes,
             `${s.builtin_recipes} ${t('admin.stat_builtin_recipes').toLowerCase()} · ${s.user_submitted_recipes} ${t('admin.stat_user_recipes').toLowerCase()}`)}
          ${this._statCard(t('admin.stat_pending_reports'), s.pending_reports,
             `${s.total_reports} ${t('admin.stat_total_reports').toLowerCase()}`)}
        </div>`;
    } catch (err) {
      document.getElementById('admin-stats-wrap').innerHTML =
        `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  _statCard(label, value, sub = '') {
    return `
      <div class="admin-stat-card">
        <div class="admin-stat-label">${this._esc(label)}</div>
        <div class="admin-stat-value">${value ?? 0}</div>
        ${sub ? `<div class="admin-stat-sub">${this._esc(sub)}</div>` : ''}
      </div>`;
  },

  /* ── Reports ─────────────────────────────────────────────────── */

  async _renderReports() {
    const el = document.getElementById('admin-page-reports');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('admin.reports_title')}</h2></div>
      </div>
      <div class="card">
        <div id="admin-reports-list">
          <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
        </div>
      </div>`;

    await this._loadReports();
  },

  async _loadReports() {
    const el = document.getElementById('admin-reports-list');
    if (!el) return;
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';

    try {
      const reports = await API.adminGetMissingRecipes();
      this._reportsById = new Map(reports.map(r => [String(r.id), r]));
      if (!reports.length) {
        el.innerHTML = `<div style="color:var(--text-3);text-align:center;padding:20px">${t('admin.no_reports')}</div>`;
        return;
      }
      el.innerHTML = `
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${t('admin.report_id')}</th>
                <th>${t('admin.report_user')}</th>
                <th>${t('admin.report_ingredients')}</th>
                <th>${t('admin.report_time')}</th>
                <th>${t('admin.report_status')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${reports.map(r => `
                <tr>
                  <td style="color:var(--text-3)">#${r.id}</td>
                  <td>${this._esc(r.username)}</td>
                  <td>
                    <div class="admin-ingredients-preview">${this._esc(r.ingredients_query)}</div>
                  </td>
                  <td style="white-space:nowrap;font-size:0.78rem;color:var(--text-3)">
                    ${r.reported_at ? new Date(r.reported_at).toLocaleDateString(isZh ? 'zh-CN' : 'en-US') : '--'}
                  </td>
                  <td>
                    <span class="admin-status-badge admin-status-${r.status}">
                      ${r.status === 'pending' ? t('admin.status_pending') : t('admin.status_reviewed')}
                    </span>
                  </td>
                  <td style="white-space:nowrap">
                    ${r.status === 'pending' ? `
                      <button class="btn btn-ghost btn-sm" data-admin-mark-reviewed="${r.id}">
                        ${t('admin.mark_reviewed')}
                      </button>
                      <button class="btn btn-sm btn-primary" style="margin-left:4px"
                        data-admin-add-report="${r.id}">
                        ${t('admin.add_recipe_from_report')}
                      </button>` : ''}
                  </td>
                </tr>`
              ).join('')}
            </tbody>
          </table>
        </div>`;
      el.querySelectorAll('[data-admin-mark-reviewed]').forEach(btn => {
        btn.addEventListener('click', () => this._markReviewed(parseInt(btn.dataset.adminMarkReviewed, 10)));
      });
      el.querySelectorAll('[data-admin-add-report]').forEach(btn => {
        btn.addEventListener('click', () => this._addRecipeFromReport(parseInt(btn.dataset.adminAddReport, 10)));
      });
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  async _markReviewed(reportId) {
    try {
      await API.adminUpdateReport(reportId, 'reviewed');
      App.showToast(I18n.lang === 'zh' ? '已标记为已处理' : 'Marked as reviewed', 'success');
      await this._loadReports();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _addRecipeFromReport(reportId) {
    const report = this._reportsById.get(String(reportId));
    this._showAddRecipeModal(report?.ingredients_query || '', reportId);
  },

  /* ── Recipes ─────────────────────────────────────────────────── */

  async _renderRecipes() {
    const el = document.getElementById('admin-page-recipes');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('admin.recipes_title')}</h2></div>
        <button class="btn btn-primary btn-sm" onclick="AdminPortal._showAddRecipeModal()">
          + ${t('admin.save_recipe')}
        </button>
      </div>
      <div class="card">
        <div id="admin-recipes-list">
          <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
        </div>
      </div>`;

    await this._loadRecipes();
  },

  async _loadRecipes() {
    const el = document.getElementById('admin-recipes-list');
    if (!el) return;
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';

    try {
      const recipes = await API.adminGetRecipes();
      if (!recipes.length) {
        el.innerHTML = `<div style="color:var(--text-3);text-align:center;padding:20px">${t('admin.no_recipes')}</div>`;
        return;
      }
      el.innerHTML = `
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${t('admin.report_id')}</th>
                <th>${t('admin.recipe_name')}</th>
                <th>${t('admin.recipe_category')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${recipes.map(r => `
                <tr>
                  <td style="color:var(--text-3)">#${r.id}</td>
                  <td>
                    ${this._esc(r.name)}
                    ${r.is_builtin ? `<span class="admin-builtin-badge">${t('admin.builtin_badge')}</span>` : ''}
                  </td>
                  <td style="color:var(--text-3)">${this._esc(r.category || '--')}</td>
                  <td style="white-space:nowrap">
                    <button class="btn btn-ghost btn-sm" onclick="AdminPortal._showEditRecipeModal(${r.id})">
                      ${isZh ? '编辑' : 'Edit'}
                    </button>
                    ${!r.is_builtin ? `
                      <button class="btn btn-ghost btn-sm" style="color:var(--rust);margin-left:4px"
                        onclick="AdminPortal._deleteRecipe(${r.id})">
                        ${t('admin.delete_recipe')}
                      </button>` : ''}
                  </td>
                </tr>`
              ).join('')}
            </tbody>
          </table>
        </div>`;
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  _showAddRecipeModal(prefillIngredients = '', reportId = null) {
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';
    App.openModal(
      t('admin.save_recipe'),
      `<div style="display:flex;flex-direction:column;gap:10px;font-size:0.85rem">
         ${reportId ? `<input type="hidden" id="ar-report-id" value="${reportId}">` : ''}
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_name')} *</label>
           <input id="ar-name" class="form-control" placeholder="${isZh ? '菜谱名称' : 'Recipe name'}">
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_category')}</label>
           <input id="ar-category" class="form-control" placeholder="${isZh ? '炒菜、炖菜…' : 'Stir-fry, Stew…'}">
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_ingredients')}</label>
           <textarea id="ar-ingredients" class="form-textarea" rows="4">${this._esc(prefillIngredients)}</textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_steps')}</label>
           <textarea id="ar-steps" class="form-textarea" rows="4"></textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_video')}</label>
           <input id="ar-video" class="form-control" placeholder="https://...">
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="AdminPortal._saveNewRecipe()">${t('admin.save_recipe')}</button>`
    );
  },

  async _saveNewRecipe() {
    const name = document.getElementById('ar-name')?.value.trim();
    const isZh = I18n.lang === 'zh';
    if (!name) {
      App.showToast(isZh ? '请输入菜谱名称' : 'Enter a recipe name', 'error');
      return;
    }
    const reportId = document.getElementById('ar-report-id')?.value || null;
    try {
      await API.adminCreateRecipe({
        name,
        category: document.getElementById('ar-category')?.value.trim() || null,
        ingredients: document.getElementById('ar-ingredients')?.value.trim() || null,
        steps: document.getElementById('ar-steps')?.value.trim() || null,
        video_url: document.getElementById('ar-video')?.value.trim() || null,
      });
      if (reportId) {
        await API.adminUpdateReport(parseInt(reportId, 10), 'reviewed');
      }
      App.closeModal();
      App.showToast(isZh ? '菜谱已添加' : 'Recipe added', 'success');
      if (this._currentPage === 'recipes') await this._loadRecipes();
      if (reportId && this._currentPage === 'reports') await this._loadReports();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _showEditRecipeModal(recipeId) {
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';
    let r;
    try { r = await API.getRecipe(recipeId); } catch (err) { App.showToast(err.message, 'error'); return; }

    App.openModal(
      isZh ? '编辑菜谱' : 'Edit Recipe',
      `<div style="display:flex;flex-direction:column;gap:10px;font-size:0.85rem">
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_name')} *</label>
           <input id="er-name" class="form-control" value="${this._esc(r.name)}">
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_category')}</label>
           <input id="er-category" class="form-control" value="${this._esc(r.category || '')}">
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_ingredients')}</label>
           <textarea id="er-ingredients" class="form-textarea" rows="4">${this._esc(r.ingredients || '')}</textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_steps')}</label>
           <textarea id="er-steps" class="form-textarea" rows="4">${this._esc(r.steps || '')}</textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('admin.recipe_video')}</label>
           <input id="er-video" class="form-control" value="${this._esc(r.video_url || '')}">
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="AdminPortal._saveEditRecipe(${recipeId})">${t('common.save')}</button>`
    );
  },

  async _saveEditRecipe(recipeId) {
    const name = document.getElementById('er-name')?.value.trim();
    if (!name) { App.showToast(I18n.lang === 'zh' ? '请输入名称' : 'Enter a name', 'error'); return; }
    try {
      await API.adminUpdateRecipe(recipeId, {
        name,
        category: document.getElementById('er-category')?.value.trim() || null,
        ingredients: document.getElementById('er-ingredients')?.value.trim() || null,
        steps: document.getElementById('er-steps')?.value.trim() || null,
        video_url: document.getElementById('er-video')?.value.trim() || null,
      });
      App.closeModal();
      App.showToast(I18n.lang === 'zh' ? '已更新' : 'Updated', 'success');
      await this._loadRecipes();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _deleteRecipe(recipeId) {
    const isZh = I18n.lang === 'zh';
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">${isZh ? '确认删除此菜谱？' : 'Delete this recipe?'}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="AdminPortal._confirmDeleteRecipe(${recipeId})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmDeleteRecipe(recipeId) {
    App.closeModal();
    try {
      await API.adminDeleteRecipe(recipeId);
      App.showToast(I18n.lang === 'zh' ? '已删除' : 'Deleted', 'success');
      await this._loadRecipes();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  /* ── Users ───────────────────────────────────────────────────── */

  async _renderUsers() {
    const el = document.getElementById('admin-page-users');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('admin.users_title')}</h2></div>
      </div>
      <div class="card">
        <div id="admin-users-list">
          <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
        </div>
      </div>`;

    await this._loadUsers();
  },

  async _loadUsers() {
    const el = document.getElementById('admin-users-list');
    if (!el) return;
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';
    const selfId = this._currentAdmin?.id;

    try {
      const users = await API.adminGetUsers();
      this._usersById = new Map(users.map(u => [String(u.id), u]));
      if (!users.length) {
        el.innerHTML = `<div style="color:var(--text-3);text-align:center;padding:20px">${t('admin.no_users')}</div>`;
        return;
      }

      el.innerHTML = `
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${t('admin.user_id')}</th>
                <th>${t('admin.user_name')}</th>
                <th>${t('admin.user_email')}</th>
                <th>${t('admin.user_role')}</th>
                <th>${t('admin.user_goal')}</th>
                <th>${t('admin.user_target_weight')}</th>
                <th>${t('admin.user_membership')}</th>
                <th>${t('admin.user_created')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${users.map(u => {
                const isSelf = u.id === selfId;
                const rolePill = u.is_admin
                  ? `<span class="role-pill role-pill-admin">${t('admin.user_role_admin')}</span>`
                  : `<span class="role-pill role-pill-user">${t('admin.user_role_normal')}</span>`;
                const statusPill = u.is_active
                  ? ''
                  : `<span class="role-pill role-pill-inactive">${t('admin.user_inactive')}</span>`;
                const goalLabel = u.goal
                  ? t('bmr.goal_' + u.goal)
                  : `<span style="color:var(--text-3)">--</span>`;
                const tw = (u.target_weight_kg !== null && u.target_weight_kg !== undefined)
                  ? `${u.target_weight_kg} kg`
                  : `<span style="color:var(--text-3)">--</span>`;
                return `
                <tr>
                  <td style="color:var(--text-3)">#${u.id}</td>
                  <td>
                    ${this._esc(u.username)}
                    ${isSelf ? `<span class="admin-builtin-badge">${isZh ? '本人' : 'You'}</span>` : ''}
                  </td>
                  <td style="color:var(--text-3);font-size:0.78rem">${this._esc(u.email || '--')}</td>
                  <td>${rolePill}${statusPill}</td>
                  <td style="font-size:0.8rem">${goalLabel}</td>
                  <td style="font-size:0.8rem">${tw}</td>
                  <td>
                    <select class="form-control" style="min-width:110px;font-size:0.8rem"
                      ${isSelf ? 'disabled' : ''}
                      onchange="AdminPortal._setMembership(${u.id}, this.value)">
                      ${['free','normal','pro','pro_max'].map(lvl =>
                        `<option value="${lvl}" ${u.membership_level === lvl ? 'selected' : ''}>${I18n.t('membership.' + lvl)}</option>`
                      ).join('')}
                    </select>
                  </td>
                  <td style="color:var(--text-3);font-size:0.78rem;white-space:nowrap">
                    ${u.created_at ? new Date(u.created_at).toLocaleDateString(isZh ? 'zh-CN' : 'en-US') : '--'}
                  </td>
                  <td style="white-space:nowrap">
                    <button class="btn btn-ghost btn-sm"
                      onclick="AdminPortal._showUserDetail(${u.id})">
                      ${t('admin.user_details')}
                    </button>
                    <button class="btn btn-ghost btn-sm" style="margin-left:4px"
                      onclick="AdminPortal._showUserPreferences(${u.id})">
                      ${this._txt('偏好修复', 'Preferences')}
                    </button>
                    ${isSelf ? `<span style="color:var(--text-3);font-size:0.75rem;margin-left:4px">${t('admin.user_self_warning')}</span>` : `
                      <button class="btn btn-ghost btn-sm" style="margin-left:4px"
                        onclick="AdminPortal._toggleAdmin(${u.id}, ${!u.is_admin})">
                        ${u.is_admin ? t('admin.user_demote') : t('admin.user_promote')}
                      </button>
                      <button class="btn btn-ghost btn-sm" style="margin-left:4px"
                        onclick="AdminPortal._toggleActive(${u.id}, ${!u.is_active})">
                        ${u.is_active ? t('admin.user_deactivate') : t('admin.user_activate')}
                      </button>
                      <button class="btn btn-ghost btn-sm" style="color:var(--rust);margin-left:4px"
                        data-admin-delete-user="${u.id}">
                        ${t('admin.user_delete')}
                      </button>
                    `}
                  </td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
      el.querySelectorAll('[data-admin-delete-user]').forEach(btn => {
        btn.addEventListener('click', () => {
          const userId = parseInt(btn.dataset.adminDeleteUser, 10);
          const user = this._usersById.get(String(userId));
          this._deleteUser(userId, user?.username || '');
        });
      });
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  async _showUserDetail(userId) {
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';
    App.openModal(
      t('admin.user_details'),
      `<div id="admin-user-detail-body" style="font-size:0.85rem">
         <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${t('common.cancel')}</button>`
    );

    let d;
    try {
      d = await API.adminGetUserDetail(userId);
    } catch (err) {
      const body = document.getElementById('admin-user-detail-body');
      if (body) body.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
      return;
    }

    const body = document.getElementById('admin-user-detail-body');
    if (!body) return;

    const fmt = v => (v === null || v === undefined || v === '') ? '--' : v;
    const s = d.summary || {};
    const p = d.bmr_profile;
    const today = d.today;
    const settings = d.settings || {};
    const prefs = d.food_preferences || { total: 0, by_category: {} };
    const a7 = d.activity_7d || {};
    const lc = d.last_condition;

    const row = (label, value) => `
      <div style="display:flex;justify-content:space-between;gap:12px;padding:4px 0;border-bottom:1px solid var(--border-1);">
        <span style="color:var(--text-3)">${this._esc(label)}</span>
        <span style="color:var(--text);text-align:right">${value}</span>
      </div>`;

    const section = (title, rows) => `
      <div style="margin-top:14px">
        <div style="font-weight:600;margin-bottom:6px;color:var(--text-2)">${this._esc(title)}</div>
        ${rows.join('')}
      </div>`;

    const goalLabel = p && p.goal ? t('bmr.goal_' + p.goal) : '--';
    const activityLabel = today && today.activity_level
      ? t('bmr.activity_' + ({
          sedentary: 'sedentary',
          lightly_active: 'lightly',
          moderately_active: 'moderately',
          strength_training: 'strength',
        }[today.activity_level] || 'sedentary'))
        + (today.activity_is_default ? ` (${t('plan.default')})` : '')
      : '--';

    const prefsList = Object.keys(prefs.by_category).length
      ? Object.entries(prefs.by_category).map(([cat, n]) => `${this._esc(cat)}: ${n}`).join(' · ')
      : '--';

    body.innerHTML = `
      ${section(t('admin.section_identity'), [
        row(t('admin.user_id'), `#${s.id}`),
        row(t('admin.user_name'), this._esc(s.username || '--')),
        row(t('admin.user_email'), this._esc(s.email || '--')),
        row(t('admin.user_role'), s.is_admin ? t('admin.user_role_admin') : t('admin.user_role_normal')),
        row(t('admin.user_status'), s.is_active ? t('admin.user_active') : t('admin.user_inactive')),
        row(t('admin.user_membership'), t('membership.' + (s.membership_level || 'free'))),
        row(t('settings.language'), fmt(s.language)),
        row(t('admin.user_created'), s.created_at ? new Date(s.created_at).toLocaleString(isZh ? 'zh-CN' : 'en-US') : '--'),
      ])}

      ${section(t('admin.section_bmr'), p ? [
        row(t('bmr.age'), fmt(p.age)),
        row(t('bmr.gender'), p.gender === 'male' ? t('bmr.gender_male') : (p.gender === 'female' ? t('bmr.gender_female') : '--')),
        row(t('bmr.height'), fmt(p.height_cm)),
        row(t('bmr.weight'), fmt(p.weight_kg)),
        row(t('admin.user_goal'), goalLabel),
        row(t('admin.user_target_weight'), d.target_weight_kg !== null && d.target_weight_kg !== undefined ? `${d.target_weight_kg} kg` : '--'),
        row(t('bmr.result_bmr'), p.bmr_value ? `${Math.round(p.bmr_value)} kcal` : '--'),
      ] : [`<div style="color:var(--text-3);padding:6px 0">${t('admin.no_bmr_profile')}</div>`])}

      ${today ? section(t('admin.section_today'), [
        row(t('bmr.activity'), activityLabel),
        row(t('bmr.result_tdee'), today.tdee ? `${Math.round(today.tdee)} kcal` : '--'),
        row(t('bmr.result_target'), today.calorie_target ? `${Math.round(today.calorie_target)} kcal` : '--'),
        row(t('diet.protein'), today.protein_g !== null && today.protein_g !== undefined ? `${today.protein_g} g` : '--'),
        row(t('diet.carbs'), today.carbs_g !== null && today.carbs_g !== undefined ? `${today.carbs_g} g` : '--'),
        row(t('diet.fat'), today.fat_g !== null && today.fat_g !== undefined ? `${today.fat_g} g` : '--'),
      ]) : ''}

      ${section(t('admin.section_settings'), [
        row(t('settings.water_goal'), `${fmt(settings.daily_water_goal_ml)} ml`),
        row(t('admin.water_reminder'), `${fmt(settings.water_reminder_min)} min`),
      ])}

      ${section(t('admin.section_engagement'), [
        row(t('stats.checkin_streak'), `${d.checkin ? d.checkin.streak : 0} ${t('dash.days')}`),
        row(t('admin.checked_in_today'), d.checkin && d.checkin.checked_in_today ? (isZh ? '是' : 'Yes') : (isZh ? '否' : 'No')),
        row(t('admin.water_logs_7d'), a7.water_logs || 0),
        row(t('admin.exercise_logs_7d'), a7.exercise_logs || 0),
        row(t('admin.diet_logs_7d'), a7.diet_logs || 0),
        row(t('admin.condition_logs_7d'), a7.condition_logs || 0),
      ])}

      ${section(t('admin.section_prefs'), [
        row(t('admin.prefs_total'), prefs.total),
        row(t('admin.prefs_by_cat'), prefsList),
      ])}

      ${lc ? section(t('admin.section_last_condition'), [
        row(t('admin.report_time'), lc.date),
        row(t('condition.weight'), lc.weight_kg !== null && lc.weight_kg !== undefined ? `${lc.weight_kg} kg` : '--'),
      ]) : ''}
    `;
  },

  async _toggleAdmin(userId, makeAdmin) {
    try {
      await API.adminUpdateUser(userId, { is_admin: makeAdmin });
      App.showToast(I18n.lang === 'zh' ? '已更新' : 'Updated', 'success');
      await this._loadUsers();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _toggleActive(userId, makeActive) {
    try {
      await API.adminUpdateUser(userId, { is_active: makeActive });
      App.showToast(I18n.lang === 'zh' ? '已更新' : 'Updated', 'success');
      await this._loadUsers();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _setMembership(userId, level) {
    try {
      await API.adminUpdateUser(userId, { membership_level: level });
      App.showToast(I18n.lang === 'zh' ? '已更新' : 'Updated', 'success');
    } catch (err) {
      App.showToast(err.message, 'error');
      await this._loadUsers();
    }
  },

  _deleteUser(userId, username) {
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">
         ${I18n.t('admin.user_delete_confirm')}<br>
         <strong style="color:var(--text)">${this._esc(username)}</strong>
       </p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="AdminPortal._confirmDeleteUser(${userId})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmDeleteUser(userId) {
    App.closeModal();
    try {
      await API.adminDeleteUser(userId);
      App.showToast(I18n.lang === 'zh' ? '用户已删除' : 'User deleted', 'success');
      await this._loadUsers();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  /* ── Utility ─────────────────────────────────────────────────── */

  async _showUserPreferences(userId) {
    App.openModal(
      this._txt('用户偏好修复', 'User Preference Repair'),
      `<div id="admin-pref-body" style="font-size:0.85rem">
         <div style="color:var(--text-3);text-align:center;padding:20px">${I18n.t('common.loading')}</div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="AdminPortal._saveUserPreferences(${userId})">${I18n.t('common.save')}</button>`
    );

    let data;
    try {
      data = await API.adminGetUserPreferences(userId);
    } catch (err) {
      const body = document.getElementById('admin-pref-body');
      if (body) body.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
      return;
    }
    this._activePreferencePayload = data;

    const body = document.getElementById('admin-pref-body');
    if (!body) return;
    const known = data.known || {};
    const selected = data.categories || {};
    const labels = data.known_labels || {};
    const audit = data.nutrition_audit || {};
    const status = audit.validation?.overall || 'unknown';
    const suggestions = (audit.suggestions || []).slice(0, 4);

    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:14px;max-height:62vh;overflow:auto;padding-right:4px">
        <div style="background:var(--surface-2);border:1px solid var(--border-1);border-radius:14px;padding:12px">
          <strong>${this._txt('闭环状态', 'Closed-loop status')}: ${this._esc(status)}</strong>
          <div style="color:var(--text-3);margin-top:6px">
            ${this._txt('管理员只修复食物偏好，不修改用户真实饮食、体重或身体记录。', 'Admins repair food preferences only. Diet logs, weight and condition records stay read-only.')}
          </div>
          ${suggestions.length ? `<div style="margin-top:8px;color:var(--text-2)">
            ${suggestions.map(s => this._esc(I18n.lang === 'zh' ? (s.message_zh || s.label_zh || s.ref) : (s.message_en || s.label_en || s.ref))).join('<br>')}
          </div>` : ''}
        </div>
        ${Object.keys(known).map(category => `
          <div>
            <div style="font-weight:700;margin-bottom:8px">${this._esc(this._categoryLabel(category))}</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">
              ${known[category].map(slug => {
                const checked = (selected[category] || []).includes(slug) ? 'checked' : '';
                const label = this._prefLabel(category, slug, labels);
                return `<label style="display:flex;gap:8px;align-items:center;border:1px solid var(--border-1);border-radius:12px;padding:8px;background:var(--surface)">
                  <input type="checkbox" data-admin-pref data-category="${this._esc(category)}" data-slug="${this._esc(slug)}" ${checked}>
                  <span>${this._esc(label)}</span>
                </label>`;
              }).join('')}
            </div>
          </div>
        `).join('')}
        <div class="form-group" style="margin:0">
          <label>${this._txt('修改原因（必填，会写入审计日志）', 'Reason (required, audited)')}</label>
          <textarea id="admin-pref-reason" class="form-textarea" rows="3"
            placeholder="${this._txt('例如：用户候选池无法闭环，按推荐补齐钙源和主食。', 'Example: Candidate pool could not close the loop, adding calcium source and staple per recommendation.')}"></textarea>
        </div>
      </div>`;
  },

  async _saveUserPreferences(userId) {
    const reason = document.getElementById('admin-pref-reason')?.value.trim() || '';
    if (!reason) {
      App.showToast(this._txt('请填写修改原因', 'Please enter a reason'), 'error');
      return;
    }
    const items = Array.from(document.querySelectorAll('[data-admin-pref]:checked')).map(el => ({
      category: el.getAttribute('data-category'),
      item_key: el.getAttribute('data-slug'),
    }));
    try {
      await API.adminUpdateUserPreferences(userId, { items, replace: true, reason });
      App.closeModal();
      App.showToast(this._txt('偏好已更新', 'Preferences updated'), 'success');
      if (this._currentPage === 'users') await this._loadUsers();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _renderOps() {
    const el = document.getElementById('admin-page-ops');
    if (!el) return;
    el.innerHTML = `
      <div class="page-header">
        <div>
          <h2>${this._txt('运营控制', 'Operations Control')}</h2>
          <p style="color:var(--text-3);margin-top:4px">
            ${this._txt('处理额度、闭环食物库和失败事件，不直接改用户真实健康记录。', 'Manage quotas, food-library loop checks and failures without editing real health records.')}
          </p>
        </div>
      </div>
      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px">
          <h3 style="margin:0">${this._txt('LLM 额度', 'LLM Quotas')}</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn-ghost btn-sm" onclick="AdminPortal._resetAllPoolQuota()">${this._txt('恢复全部候选池次数', 'Reset all pool naming')}</button>
            <button class="btn btn-ghost btn-sm" onclick="AdminPortal._loadQuotaPanel()">${this._txt('刷新', 'Refresh')}</button>
          </div>
        </div>
        <div id="admin-quota-panel">${this._loading()}</div>
      </div>
      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px">
          <h3 style="margin:0">${this._txt('食物库闭环', 'Food Library Loop')}</h3>
          <button class="btn btn-ghost btn-sm" onclick="AdminPortal._loadFoodLibraryPanel()">${this._txt('刷新', 'Refresh')}</button>
        </div>
        <div id="admin-library-panel">${this._loading()}</div>
      </div>
      <div class="card">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px">
          <h3 style="margin:0">${this._txt('失败事件', 'Failure Events')}</h3>
          <button class="btn btn-ghost btn-sm" onclick="AdminPortal._loadEventsPanel()">${this._txt('刷新', 'Refresh')}</button>
        </div>
        <div id="admin-events-panel">${this._loading()}</div>
      </div>`;
    this._loadQuotaPanel();
    this._loadFoodLibraryPanel();
    this._loadEventsPanel();
  },

  async _loadQuotaPanel() {
    const el = document.getElementById('admin-quota-panel');
    if (!el) return;
    try {
      const data = await API.adminGetLLMQuotas();
      const rows = data.users || [];
      if (!rows.length) {
        el.innerHTML = `<div style="color:var(--text-3);padding:12px">${this._txt('暂无用户', 'No users')}</div>`;
        return;
      }
      el.innerHTML = `
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${this._txt('用户', 'User')}</th>
                <th>${this._txt('候选池命名', 'Pool naming')}</th>
                <th>${this._txt('菜谱建议', 'Recipe suggest')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(row => {
                const user = row.user || {};
                const quotas = row.quotas || {};
                return `<tr>
                  <td>
                    <strong>${this._esc(user.username || '--')}</strong>
                    <div style="color:var(--text-3);font-size:0.78rem">#${user.id} · ${this._esc(user.membership_level || 'free')}</div>
                  </td>
                  <td>${this._quotaCell(quotas.pool_name)}</td>
                  <td>${this._quotaCell(quotas.recipe_suggest)}</td>
                  <td style="white-space:nowrap">
                    <button class="btn btn-ghost btn-sm" onclick="AdminPortal._resetQuota(${user.id}, 'pool_name')">${this._txt('重置命名', 'Reset naming')}</button>
                    <button class="btn btn-ghost btn-sm" style="margin-left:4px" onclick="AdminPortal._resetQuota(${user.id}, 'recipe_suggest')">${this._txt('重置建议', 'Reset suggest')}</button>
                  </td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  _quotaCell(q) {
    if (!q) return '--';
    const next = q.next_refresh_at ? new Date(q.next_refresh_at).toLocaleString(I18n.lang === 'zh' ? 'zh-CN' : 'en-US') : '--';
    return `<strong>${q.used || 0}/${q.limit || 0}</strong>
      <div style="color:var(--text-3);font-size:0.78rem">${this._txt('剩余', 'Remaining')}: ${q.remaining || 0}</div>
      <div style="color:var(--text-3);font-size:0.74rem">${this._txt('恢复', 'Refresh')}: ${this._esc(next)}</div>`;
  },

  _resetQuota(userId, kind) {
    App.openModal(
      this._txt('重置 LLM 额度', 'Reset LLM Quota'),
      `<div class="form-group" style="margin:0">
         <label>${this._txt('原因（必填，会写入审计日志）', 'Reason (required, audited)')}</label>
         <textarea id="admin-quota-reason" class="form-textarea" rows="3"
           placeholder="${this._txt('例如：LLM 返回乱码，已人工确认需要补偿一次。', 'Example: LLM returned unusable output; compensate one quota cycle.')}"></textarea>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="AdminPortal._confirmResetQuota(${userId}, '${kind}')">${this._txt('确认重置', 'Confirm reset')}</button>`
    );
  },

  _resetAllPoolQuota() {
    App.openModal(
      this._txt('恢复全部候选池次数', 'Reset All Pool Naming'),
      `<div style="color:var(--text-2);font-size:0.88rem;margin-bottom:12px">
         ${this._txt(
           '将恢复所有用户的候选池命名次数；不会影响菜谱建议额度，也不会修改真实健康记录。',
           'This resets pool-naming quota for every user. Recipe-suggestion quota and real health records are not changed.'
         )}
       </div>
       <div class="form-group" style="margin:0">
         <label>${this._txt('原因（必填，会写入审计日志）', 'Reason (required, audited)')}</label>
         <textarea id="admin-quota-reset-all-reason" class="form-textarea" rows="3"
           placeholder="${this._txt('例如：候选池命名额度异常，需要统一恢复。', 'Example: Pool naming quota behaved incorrectly; restore all users.')}"></textarea>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="AdminPortal._confirmResetAllPoolQuota()">${this._txt('确认恢复', 'Confirm reset')}</button>`
    );
  },

  async _confirmResetQuota(userId, kind) {
    const reason = document.getElementById('admin-quota-reason')?.value.trim() || '';
    if (!reason) {
      App.showToast(this._txt('请填写重置原因', 'Please enter a reset reason'), 'error');
      return;
    }
    try {
      await API.adminResetLLMQuota(userId, { kind, reason });
      App.closeModal();
      App.showToast(this._txt('额度已重置', 'Quota reset'), 'success');
      await this._loadQuotaPanel();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _confirmResetAllPoolQuota() {
    const reason = document.getElementById('admin-quota-reset-all-reason')?.value.trim() || '';
    if (!reason) {
      App.showToast(this._txt('请填写重置原因', 'Please enter a reset reason'), 'error');
      return;
    }
    try {
      const result = await API.adminResetAllLLMQuotas({ kind: 'pool_name', reason });
      App.closeModal();
      App.showToast(
        this._txt(
          `已恢复 ${result.affected_user_count || 0} 个用户的候选池次数`,
          `Reset pool naming for ${result.affected_user_count || 0} users`
        ),
        'success'
      );
      await this._loadQuotaPanel();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _loadFoodLibraryPanel() {
    const el = document.getElementById('admin-library-panel');
    if (!el) return;
    try {
      const data = await API.adminGetFoodLibrary();
      const buckets = Object.entries(data.validation_buckets || {});
      el.innerHTML = `
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
          <span class="badge">${this._txt('食物数', 'Foods')}: ${data.total_foods || 0}</span>
          <span class="badge">${this._txt('校验桶', 'Validation buckets')}: ${buckets.length}</span>
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${this._txt('闭环类别', 'Loop bucket')}</th>
                <th>${this._txt('食物数', 'Foods')}</th>
                <th>${this._txt('性质', 'Type')}</th>
                <th>${this._txt('示例', 'Examples')}</th>
              </tr>
            </thead>
            <tbody>
              ${buckets.map(([key, bucket]) => `
                <tr>
                  <td><strong>${this._esc(I18n.lang === 'zh' ? bucket.label_zh : bucket.label_en)}</strong><div style="color:var(--text-3);font-size:0.75rem">${this._esc(key)}</div></td>
                  <td>${bucket.count || 0}</td>
                  <td>${bucket.is_blocking ? this._txt('阻断生成', 'Blocking') : this._txt('软缺口', 'Soft gap')}</td>
                  <td style="color:var(--text-3);font-size:0.78rem">${this._esc((bucket.slugs || []).slice(0, 6).join(', '))}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  async _loadEventsPanel() {
    const el = document.getElementById('admin-events-panel');
    if (!el) return;
    try {
      const data = await API.adminGetObservabilityEvents({ limit: 80 });
      const events = data.items || [];
      if (!events.length) {
        el.innerHTML = `<div style="color:var(--text-3);padding:12px">${this._txt('暂无事件', 'No events')}</div>`;
        return;
      }
      el.innerHTML = `
        <div style="color:var(--text-3);font-size:0.78rem;margin-bottom:10px">${this._txt('来源', 'Source')}: ${this._esc(data.source || '--')}</div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>${this._txt('时间', 'Time')}</th>
                <th>${this._txt('级别', 'Level')}</th>
                <th>${this._txt('用户', 'User')}</th>
                <th>${this._txt('事件', 'Event')}</th>
                <th>${this._txt('摘要', 'Summary')}</th>
              </tr>
            </thead>
            <tbody>
              ${events.map(e => `
                <tr>
                  <td style="white-space:nowrap;color:var(--text-3);font-size:0.78rem">${this._esc(e.ts || '--')}</td>
                  <td>${this._esc(e.lvl || '--')}</td>
                  <td>${this._esc(String(e.user_id ?? '--'))}</td>
                  <td>
                    <strong>${this._esc(e.event || e.path || e.logger || '--')}</strong>
                    <div style="color:var(--text-3);font-size:0.74rem">${this._esc(e.request_id || '')}</div>
                  </td>
                  <td style="max-width:520px;color:var(--text-2);font-size:0.82rem">${this._esc(e.msg || '--')}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch (err) {
      el.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  _loading() {
    return `<div style="color:var(--text-3);text-align:center;padding:20px">${I18n.t('common.loading')}</div>`;
  },

  _txt(zh, en) {
    return I18n.lang === 'zh' ? zh : en;
  },

  _categoryLabel(category) {
    const labels = {
      grains: this._txt('主食', 'Grains'),
      vegetables: this._txt('蔬菜/菌菇/海藻', 'Vegetables / fungi / algae'),
      fruits: this._txt('水果', 'Fruits'),
      meat_low_fat: this._txt('低脂肉类', 'Low-fat protein'),
      meat_mid_fat: this._txt('中脂肉类/海产', 'Mid-fat protein / seafood'),
      soy: this._txt('豆制品', 'Soy'),
      dairy: this._txt('乳制品', 'Dairy'),
      nuts: this._txt('坚果/种子/油脂', 'Nuts / seeds / oils'),
    };
    return labels[category] || category;
  },

  _prefLabel(category, slug, labels) {
    const label = labels?.[category]?.[slug];
    if (label) return I18n.lang === 'zh' ? (label.zh || slug) : (label.en || slug);
    return slug;
  },

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,"&#39;");
  },
};
