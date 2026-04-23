/* ============================================================
   Compass Health — pages/settings.js
   Settings page
   ============================================================ */

const SettingsPage = {
  _user: null,
  _settings: null,
  _bmr: null,

  async render() {
    const container = document.getElementById('page-settings');
    if (!container) return;

    container.innerHTML = `<div class="loading-state"><span class="spinner"></span> <span data-i18n="common.loading">加载中...</span></div>`;

    try {
      const [userRes, settingsRes, bmrRes] = await Promise.allSettled([
        API.getMe(),
        API.getSettings(),
        API.getBMR()
      ]);

      this._user     = userRes.status     === 'fulfilled' ? userRes.value     : {};
      this._settings = settingsRes.status === 'fulfilled' ? settingsRes.value : {};
      this._bmr      = bmrRes.status      === 'fulfilled' ? bmrRes.value      : null;

      this._renderContent(container);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">${I18n.t('common.error')}: ${err.message}</div>`;
    }
  },

  _renderContent(container) {
    const u = this._user     || {};
    const s = this._settings || {};
    const b = this._bmr      || null;

    const level = u.membership_level || 'free';
    const levelIcons = { free: '🆓', normal: '🌟', pro: '💎', pro_max: '👑' };
    const levelKey   = { free: 'settings.mem_free', normal: 'settings.mem_normal', pro: 'settings.mem_pro', pro_max: 'settings.mem_promax' };

    const waterGoal = s.water_goal_ml || u.water_goal_ml || 2000;

    container.innerHTML = `
      <div class="page-header">
        <h2 class="page-title" data-i18n="settings.title">设置</h2>
      </div>

      <div class="grid-2">
        <div style="display:flex;flex-direction:column;gap:20px;">

          <!-- Membership -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.membership">会员等级</div>
            <div class="membership-display">
              <div class="membership-icon">${levelIcons[level] || '🆓'}</div>
              <div class="membership-info">
                <div class="membership-name">
                  <span class="badge badge-${level}" style="margin-right:8px;">${I18n.t(`membership.${level}`)}</span>
                  <span data-i18n="${levelKey[level] || 'settings.mem_free'}">${I18n.t(levelKey[level] || 'settings.mem_free')}</span>
                </div>
                ${level === 'free'
                  ? `<div class="membership-hint" data-i18n="membership.upgrade_hint">${I18n.t('membership.upgrade_hint')}</div>`
                  : ''
                }
              </div>
            </div>
          </div>

          <!-- Profile -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.profile">个人信息</div>
            <div class="form-group">
              <label class="form-label">${I18n.lang === 'zh' ? '用户名' : 'Username'}</label>
              <input type="text" class="form-input" value="${this._escHtml(u.username || '')}" readonly
                     style="background:var(--surface-2);cursor:default;">
            </div>
            <div class="form-group">
              <label class="form-label">${I18n.lang === 'zh' ? '邮箱' : 'Email'}</label>
              <input type="email" class="form-input" value="${this._escHtml(u.email || '')}" readonly
                     style="background:var(--surface-2);cursor:default;">
            </div>
          </div>

          <!-- BMR Profile -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.bmr_profile">BMR 健康档案</div>
            ${b ? `
              <div class="grid-2" style="margin-bottom:14px;">
                <div style="background:var(--surface-2);border-radius:var(--radius);padding:12px;text-align:center;">
                  <div style="font-size:0.72rem;color:var(--text-3);" data-i18n="bmr.result_bmr">基础代谢率</div>
                  <div id="settings-bmr-val" style="font-size:1.4rem;font-family:'Fraunces',serif;color:var(--accent);">${Math.round(b.bmr_value || 0)}</div>
                  <div style="font-size:0.7rem;color:var(--text-3);">kcal</div>
                </div>
                <div style="background:var(--surface-2);border-radius:var(--radius);padding:12px;text-align:center;">
                  <div style="font-size:0.72rem;color:var(--text-3);" data-i18n="bmr.result_tdee">每日总热量需求</div>
                  <div id="settings-tdee-val" style="font-size:1.4rem;font-family:'Fraunces',serif;color:var(--accent);">${b.tdee_value ? Math.round(b.tdee_value) : '—'}</div>
                  <div style="font-size:0.7rem;color:var(--text-3);">kcal</div>
                </div>
              </div>
              <div class="form-group">
                <label class="form-label" data-i18n="settings.current_weight">当前体重 (kg)</label>
                <input type="number" id="setting-weight" class="form-input"
                       min="30" max="300" step="0.1" value="${b.weight_kg != null ? b.weight_kg : ''}">
                <span class="form-error" id="weight-err"></span>
              </div>
              <button class="btn btn-ghost btn-sm" id="update-weight-btn" data-i18n="settings.update_weight">更新体重</button>
            ` : ''}
          </div>

          <!-- Food Preferences -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.food_prefs">饮食偏好</div>
            <p class="muted" style="margin:0 0 12px;" data-i18n="settings.food_prefs_hint">更新配餐可用的食材。</p>
            <button class="btn btn-ghost btn-sm" id="edit-prefs-btn" data-i18n="settings.edit_food_prefs">修改饮食偏好</button>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:20px;">

          <!-- Daily Water Goal -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.water_goal">每日饮水目标 (ml)</div>
            <div class="form-group">
              <input type="number" id="setting-water-goal" class="form-input"
                     min="500" max="10000" step="100" value="${waterGoal}">
              <span class="form-error" id="water-goal-err"></span>
            </div>
          </div>

          <!-- Language -->
          <div class="card">
            <div class="settings-section-title" data-i18n="settings.language">语言</div>
            <div class="lang-selector">
              <button type="button" class="lang-option ${I18n.lang === 'zh' ? 'selected' : ''}"
                      data-lang="zh" data-i18n="settings.lang_zh">中文</button>
              <button type="button" class="lang-option ${I18n.lang === 'en' ? 'selected' : ''}"
                      data-lang="en" data-i18n="settings.lang_en">English</button>
            </div>
          </div>

          <!-- Save button -->
          <div>
            <span class="form-error" id="settings-global-err" style="display:block;margin-bottom:8px;"></span>
            <button class="btn w-full" id="save-settings-btn" data-i18n="settings.save">保存设置</button>
          </div>
        </div>
      </div>
    `;

    I18n.apply();
    this._bindEvents();
  },

  _bindEvents() {
    // Language selection
    document.querySelectorAll('.lang-option[data-lang]').forEach(btn => {
      btn.addEventListener('click', () => {
        const lang = btn.getAttribute('data-lang');
        I18n.setLang(lang);
        // Re-render after language change
        this.render();
      });
    });

    // Update weight
    document.getElementById('update-weight-btn')?.addEventListener('click', () => {
      this._handleWeightUpdate();
    });

    // Edit food preferences — re-opens the onboarding picker pre-populated
    document.getElementById('edit-prefs-btn')?.addEventListener('click', () => {
      App.showView('preferences');
    });

    // Save settings
    document.getElementById('save-settings-btn')?.addEventListener('click', () => {
      this._handleSave();
    });
  },

  async _handleWeightUpdate() {
    const input = document.getElementById('setting-weight');
    const errEl = document.getElementById('weight-err');
    const btn = document.getElementById('update-weight-btn');

    if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }

    const weight = parseFloat(input?.value);
    if (!weight || weight < 30 || weight > 300) {
      if (errEl) {
        errEl.textContent = I18n.lang === 'zh'
          ? '请输入有效体重(30-300kg)'
          : 'Weight must be between 30 and 300 kg';
        errEl.classList.add('visible');
      }
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }

    try {
      const res = await API.updateWeight(weight);
      const bmrEl = document.getElementById('settings-bmr-val');
      const tdeeEl = document.getElementById('settings-tdee-val');
      if (bmrEl && res.bmr_value != null) bmrEl.textContent = Math.round(res.bmr_value);
      if (tdeeEl) tdeeEl.textContent = res.tdee_value != null ? Math.round(res.tdee_value) : '—';
      if (this._bmr) {
        this._bmr.weight_kg = res.weight_kg;
        this._bmr.bmr_value = res.bmr_value;
        this._bmr.tdee_value = res.tdee_value;
      }
      App.showToast(I18n.t('settings.weight_saved'), 'success');
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || I18n.t('common.error');
        errEl.classList.add('visible');
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.update_weight'); }
    }
  },

  async _handleSave() {
    const errEl = document.getElementById('settings-global-err');
    const waterGoalEl = document.getElementById('setting-water-goal');
    const waterGoalErrEl = document.getElementById('water-goal-err');

    if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }
    if (waterGoalErrEl) { waterGoalErrEl.textContent = ''; waterGoalErrEl.classList.remove('visible'); }

    const waterGoal = parseInt(waterGoalEl?.value, 10);

    if (!waterGoal || waterGoal < 500 || waterGoal > 10000) {
      if (waterGoalErrEl) {
        waterGoalErrEl.textContent = I18n.lang === 'zh'
          ? '饮水目标须在 500-10000ml 之间'
          : 'Water goal must be between 500-10000 ml';
        waterGoalErrEl.classList.add('visible');
      }
      return;
    }

    const btn = document.getElementById('save-settings-btn');
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }

    try {
      await API.saveSettings({
        water_goal_ml: waterGoal,
        language: I18n.lang
      });
      App.showToast(I18n.t('common.success'), 'success');
    } catch (err) {
      if (errEl) { errEl.textContent = err.message || I18n.t('common.error'); errEl.classList.add('visible'); }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.save'); }
    }
  },

  _escHtml(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
};
