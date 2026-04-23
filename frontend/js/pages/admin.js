/* ============================================================
   Compass Health — pages/admin.js
   Admin portal: dashboard, reports, recipes, users.
   Runs inside the dedicated #view-admin shell — no user-side
   features (water/diet/exercise/etc.) are accessible from here.
   ============================================================ */

const AdminPortal = {

  _currentPage: 'dashboard',
  _currentAdmin: null,

  /* ── Bootstrap ───────────────────────────────────────────────── */

  async init() {
    try {
      const me = await API.getMe();
      if (!me.is_admin) {
        // Non-admin reached the admin view somehow — bounce them out.
        App.showView('auth');
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
                      <button class="btn btn-ghost btn-sm" onclick="AdminPortal._markReviewed(${r.id})">
                        ${t('admin.mark_reviewed')}
                      </button>
                      <button class="btn btn-sm btn-primary" style="margin-left:4px"
                        onclick="AdminPortal._addRecipeFromReport(${r.id}, '${this._esc(r.ingredients_query)}')">
                        ${t('admin.add_recipe_from_report')}
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

  async _markReviewed(reportId) {
    try {
      await API.adminUpdateReport(reportId, 'reviewed');
      App.showToast(I18n.lang === 'zh' ? '已标记为已处理' : 'Marked as reviewed', 'success');
      await this._loadReports();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _addRecipeFromReport(reportId, ingredientsQuery) {
    this._showAddRecipeModal(ingredientsQuery, reportId);
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
                        onclick="AdminPortal._deleteUser(${u.id}, '${this._esc(u.username)}')">
                        ${t('admin.user_delete')}
                      </button>
                    `}
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

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,"&#39;");
  },
};
