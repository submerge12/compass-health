/* ============================================================
   Compass Health - pages/settings.js
   Profile center
   ============================================================ */

const SettingsPage = {
  _user: null,
  _settings: null,
  _bmr: null,
  _activity: null,

  async render() {
    const container = document.getElementById('page-settings');
    if (!container) return;

    container.innerHTML = `<div class="loading-state"><span class="spinner"></span> <span data-i18n="common.loading">Loading...</span></div>`;

    try {
      const [userRes, settingsRes, bmrRes, activityRes] = await Promise.allSettled([
        API.getMe(),
        API.getSettings(),
        API.getBMR(),
        API.getDailyActivityToday(),
      ]);

      this._user = userRes.status === 'fulfilled' ? userRes.value : {};
      this._settings = settingsRes.status === 'fulfilled' ? settingsRes.value : {};
      this._bmr = bmrRes.status === 'fulfilled' ? bmrRes.value : null;
      this._activity = activityRes.status === 'fulfilled' ? activityRes.value : null;

      this._renderContent(container);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">${this._esc(I18n.t('common.error'))}: ${this._esc(err.message)}</div>`;
    }
  },

  _renderContent(container) {
    const t = k => I18n.t(k);
    const user = this._user || {};
    const settings = this._settings || {};
    const bmr = this._bmr || null;
    const activity = this._activity || null;
    const waterGoal = settings.daily_water_goal_ml || settings.water_goal_ml || 2000;
    const profileActivity = this._profileActivityLevel();
    const activeActivity = (activity && activity.activity_level) || (bmr && bmr.activity_level) || profileActivity;

    container.innerHTML = `
      <div class="profile-center">
        <section class="profile-hero">
          <div class="profile-avatar" aria-hidden="true">${this._esc(this._avatarText(user))}</div>
          <div class="profile-identity">
            <span class="profile-kicker">${this._esc(t('settings.account_center'))}</span>
            <h2>${this._esc(user.username || user.email || t('app.name'))}</h2>
            <p>${this._esc(user.email || t('settings.email_missing'))}</p>
          </div>
          <div class="profile-membership">
            <span class="badge badge-${this._esc(user.membership_level || 'free')}">${this._esc(this._membershipLabel(user.membership_level))}</span>
            <small>${this._esc(t('settings.member_status'))}</small>
          </div>
        </section>

        <section class="profile-stat-strip">
          ${this._renderStatCard(t('settings.current_weight_short'), this._formatKg(bmr && bmr.weight_kg), t('settings.current_weight'))}
          ${this._renderStatCard(t('settings.target_weight_short'), this._formatKg(user.target_weight_kg), t('settings.target_weight_hint_short'))}
          ${this._renderStatCard(t('settings.tdee_short'), this._formatKcal(bmr && bmr.tdee_value), t('bmr.result_tdee'))}
          ${this._renderStatCard(t('settings.activity_short'), this._activityLabel(activeActivity), t('settings.activity_effect'))}
        </section>

        <div class="profile-grid">
          <section class="profile-panel profile-panel-primary">
            <div class="profile-panel-header">
              <div>
                <span class="profile-kicker">${this._esc(t('settings.health_profile'))}</span>
                <h3>${this._esc(t('settings.body_goals'))}</h3>
              </div>
              <button type="button" class="btn btn-ghost btn-sm" id="edit-bmr-btn">
                ${this._esc(bmr ? t('settings.edit_bmr') : t('settings.start_bmr'))}
              </button>
            </div>
            ${bmr ? this._renderBodyForm(bmr, user) : this._renderNoBmr()}
          </section>

          <section class="profile-panel">
            <div class="profile-panel-header">
              <div>
                <span class="profile-kicker">${this._esc(t('settings.activity_default'))}</span>
                <h3>${this._esc(this._activityLabel(profileActivity))}</h3>
              </div>
              <button type="button" class="btn btn-primary btn-sm" id="choose-activity-btn" ${bmr ? '' : 'disabled'}>
                ${this._esc(t('settings.choose_activity'))}
              </button>
            </div>
            <p class="profile-muted">${this._esc(t('settings.activity_default_hint'))}</p>
            <div class="profile-activity-status">
              <span>${this._esc(t('settings.today_activity'))}</span>
              <strong>${this._esc(this._activityLabel(activeActivity))}</strong>
              <small>${this._esc(this._activitySourceLabel(activity))}</small>
            </div>
          </section>

          <section class="profile-panel">
            <div class="profile-panel-header">
              <div>
                <span class="profile-kicker">${this._esc(t('settings.daily_settings'))}</span>
                <h3>${this._esc(t('settings.hydration_language'))}</h3>
              </div>
            </div>
            <div class="profile-form-grid">
              <div class="form-group">
                <label class="form-label" for="setting-water-goal">${this._esc(t('settings.water_goal'))}</label>
                <input type="number" id="setting-water-goal" class="form-input" min="500" max="10000" step="100" value="${this._esc(waterGoal)}">
                <span class="form-error" id="water-goal-err"></span>
              </div>
              <div class="form-group">
                <label class="form-label">${this._esc(t('settings.language'))}</label>
                <div class="lang-selector">
                  <button type="button" class="lang-option ${I18n.lang === 'zh' ? 'selected' : ''}" data-lang="zh">${this._esc(t('settings.lang_zh'))}</button>
                  <button type="button" class="lang-option ${I18n.lang === 'en' ? 'selected' : ''}" data-lang="en">${this._esc(t('settings.lang_en'))}</button>
                </div>
              </div>
            </div>
            <span class="form-error" id="settings-global-err"></span>
            <button type="button" class="btn btn-primary" id="save-settings-btn">${this._esc(t('settings.save'))}</button>
          </section>

          <section class="profile-panel">
            <div class="profile-panel-header">
              <div>
                <span class="profile-kicker">${this._esc(t('settings.food_prefs'))}</span>
                <h3>${this._esc(t('settings.meal_profile'))}</h3>
              </div>
              <button type="button" class="btn btn-ghost btn-sm" id="edit-prefs-btn">
                ${this._esc(t('settings.edit_food_prefs'))}
              </button>
            </div>
            <p class="profile-muted">${this._esc(t('settings.food_prefs_hint'))}</p>
          </section>
        </div>
      </div>
    `;

    this._bindEvents();
    I18n.apply();
  },

  _renderBodyForm(bmr, user) {
    const t = k => I18n.t(k);
    const goal = this._goalLabel(bmr.goal);
    return `
      <div class="profile-form-grid">
        <div class="form-group">
          <label class="form-label" for="setting-weight">${this._esc(t('settings.current_weight'))}</label>
          <input type="number" id="setting-weight" class="form-input" min="30" max="300" step="0.1" value="${bmr.weight_kg != null ? this._esc(bmr.weight_kg) : ''}">
          <span class="form-error" id="weight-err"></span>
        </div>
        <div class="form-group">
          <label class="form-label" for="setting-target-weight">${this._esc(t('settings.target_weight'))}</label>
          <input type="number" id="setting-target-weight" class="form-input" min="20" max="300" step="0.1" value="${user.target_weight_kg != null ? this._esc(user.target_weight_kg) : ''}" placeholder="${this._esc(t('settings.target_weight_placeholder'))}">
          <span class="form-error" id="target-weight-err"></span>
        </div>
      </div>
      <div class="profile-bmr-metrics">
        <div>
          <span>${this._esc(t('bmr.result_bmr'))}</span>
          <strong id="settings-bmr-val">${this._esc(this._formatNumber(bmr.bmr_value))}</strong>
          <small>${this._esc(t('common.kcal'))}</small>
        </div>
        <div>
          <span>${this._esc(t('bmr.result_tdee'))}</span>
          <strong id="settings-tdee-val">${this._esc(this._formatNumber(bmr.tdee_value))}</strong>
          <small>${this._esc(t('common.kcal'))}</small>
        </div>
        <div>
          <span>${this._esc(t('bmr.goal'))}</span>
          <strong>${this._esc(goal)}</strong>
          <small>${this._esc(t('settings.goal_status'))}</small>
        </div>
      </div>
      <div class="profile-action-row">
        <button type="button" class="btn btn-primary btn-sm" id="update-weight-btn">${this._esc(t('settings.update_weight'))}</button>
        <button type="button" class="btn btn-ghost btn-sm" id="update-target-weight-btn">${this._esc(t('settings.update_target_weight'))}</button>
      </div>
    `;
  },

  _renderNoBmr() {
    const t = k => I18n.t(k);
    return `
      <div class="profile-empty">
        <strong>${this._esc(t('settings.no_bmr_title'))}</strong>
        <span>${this._esc(t('settings.no_bmr_hint'))}</span>
      </div>
    `;
  },

  _renderStatCard(label, value, hint) {
    return `
      <div class="profile-stat-card">
        <span>${this._esc(label)}</span>
        <strong>${this._esc(value || '--')}</strong>
        <small>${this._esc(hint)}</small>
      </div>
    `;
  },

  _bindEvents() {
    document.querySelectorAll('.lang-option[data-lang]').forEach(btn => {
      btn.addEventListener('click', () => {
        I18n.setLang(btn.getAttribute('data-lang'));
      });
    });

    document.getElementById('edit-bmr-btn')?.addEventListener('click', () => {
      App.showView('bmr-wizard');
    });

    document.getElementById('choose-activity-btn')?.addEventListener('click', () => {
      this._openActivityModal();
    });

    document.getElementById('update-weight-btn')?.addEventListener('click', () => {
      this._handleWeightUpdate();
    });

    document.getElementById('update-target-weight-btn')?.addEventListener('click', () => {
      this._handleTargetWeightUpdate();
    });

    document.getElementById('edit-prefs-btn')?.addEventListener('click', () => {
      App.showView('preferences');
    });

    document.getElementById('save-settings-btn')?.addEventListener('click', () => {
      this._handleSave();
    });
  },

  _openActivityModal() {
    if (!this._bmr) {
      App.showToast(I18n.t('settings.no_bmr_hint'), 'info');
      return;
    }

    const t = k => I18n.t(k);
    const options = this._activityOptions();
    let selected = this._profileActivityLevel();

    const content = `
      <div class="activity-choice-list">
        ${options.map(option => `
          <button type="button" class="activity-choice ${option.value === selected ? 'selected' : ''}" data-activity="${this._esc(option.value)}">
            <span class="activity-choice-name">${this._esc(option.label)}</span>
            <span class="activity-choice-desc">${this._esc(option.desc)}</span>
            <strong>${this._esc(option.multiplier)}</strong>
          </button>
        `).join('')}
      </div>
      <p class="profile-modal-hint">${this._esc(t('settings.activity_modal_hint'))}</p>
      <span class="form-error" id="activity-modal-err"></span>
    `;
    const footer = `
      <button type="button" class="btn btn-ghost" id="activity-cancel-btn">${this._esc(t('common.cancel'))}</button>
      <button type="button" class="btn btn-primary" id="activity-save-btn">${this._esc(t('settings.activity_save'))}</button>
    `;

    App.openModal(t('settings.activity_modal_title'), content, footer);

    document.querySelectorAll('.activity-choice[data-activity]').forEach(btn => {
      btn.addEventListener('click', () => {
        selected = btn.getAttribute('data-activity');
        document.querySelectorAll('.activity-choice').forEach(item => item.classList.remove('selected'));
        btn.classList.add('selected');
      });
    });

    document.getElementById('activity-cancel-btn')?.addEventListener('click', () => App.closeModal());
    document.getElementById('activity-save-btn')?.addEventListener('click', () => {
      this._handleActivitySave(selected);
    });
  },

  async _handleActivitySave(activityLevel) {
    const btn = document.getElementById('activity-save-btn');
    const errEl = document.getElementById('activity-modal-err');
    if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }

    try {
      const res = await API.updateActivityLevel(activityLevel);
      if (this._bmr) {
        this._bmr.profile_activity_level = res.activity_level;
        this._bmr.activity_level = (res.daily_targets && res.daily_targets.activity_level) || res.activity_level;
        this._bmr.tdee_value = res.tdee_value;
        this._bmr.daily_targets = res.daily_targets || this._bmr.daily_targets;
      }
      if (this._activity && !this._activity.is_logged) {
        this._activity.default_activity = res.activity_level;
        this._activity.activity_level = res.activity_level;
      }
      App.closeModal();
      const container = document.getElementById('page-settings');
      if (container) this._renderContent(container);
      App.showToast(I18n.t('settings.activity_saved'), 'success');
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || I18n.t('common.error');
        errEl.classList.add('visible');
      } else {
        App.showToast(err.message || I18n.t('common.error'), 'error');
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.activity_save'); }
    }
  },

  async _handleWeightUpdate() {
    const input = document.getElementById('setting-weight');
    const errEl = document.getElementById('weight-err');
    const btn = document.getElementById('update-weight-btn');
    if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }

    const weight = parseFloat(input?.value);
    if (!weight || weight < 30 || weight > 300) {
      this._showFieldError(errEl, I18n.t('settings.weight_invalid'));
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      const res = await API.updateWeight(weight);
      this._bmr = {
        ...(this._bmr || {}),
        weight_kg: res.weight_kg,
        bmr_value: res.bmr_value,
        tdee_value: res.tdee_value,
      };
      const bmrValEl = document.getElementById('settings-bmr-val');
      const tdeeValEl = document.getElementById('settings-tdee-val');
      if (bmrValEl) bmrValEl.textContent = this._formatNumber(res.bmr_value);
      if (tdeeValEl) tdeeValEl.textContent = this._formatNumber(res.tdee_value);
      const container = document.getElementById('page-settings');
      if (container) this._renderContent(container);
      App.showToast(I18n.t('settings.weight_saved'), 'success');
    } catch (err) {
      this._showFieldError(errEl, err.message || I18n.t('common.error'));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.update_weight'); }
    }
  },

  async _handleTargetWeightUpdate() {
    const input = document.getElementById('setting-target-weight');
    const errEl = document.getElementById('target-weight-err');
    const btn = document.getElementById('update-target-weight-btn');
    if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }

    const rawValue = (input?.value || '').trim();
    const targetWeight = rawValue === '' ? null : parseFloat(rawValue);
    if (targetWeight !== null && (!targetWeight || targetWeight < 20 || targetWeight > 300)) {
      this._showFieldError(errEl, I18n.t('settings.target_weight_invalid'));
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      const res = await API.updateTargetWeight(targetWeight);
      this._user = {
        ...(this._user || {}),
        target_weight_kg: res.target_weight_kg,
      };
      const container = document.getElementById('page-settings');
      if (container) this._renderContent(container);
      App.showToast(I18n.t('settings.target_weight_saved'), 'success');
    } catch (err) {
      this._showFieldError(errEl, err.message || I18n.t('common.error'));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.update_target_weight'); }
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
      this._showFieldError(waterGoalErrEl, I18n.t('settings.water_goal_invalid'));
      return;
    }

    const btn = document.getElementById('save-settings-btn');
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      await API.saveSettings({
        daily_water_goal_ml: waterGoal,
        language: I18n.lang,
      });
      this._settings = {
        ...(this._settings || {}),
        daily_water_goal_ml: waterGoal,
        language: I18n.lang,
      };
      App.showToast(I18n.t('common.success'), 'success');
    } catch (err) {
      this._showFieldError(errEl, err.message || I18n.t('common.error'));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('settings.save'); }
    }
  },

  _activityOptions() {
    return [
      {
        value: 'sedentary',
        label: I18n.t('bmr.activity_sedentary'),
        desc: I18n.t('settings.activity_sedentary_desc'),
        multiplier: 'x1.10',
      },
      {
        value: 'lightly_active',
        label: I18n.t('bmr.activity_lightly'),
        desc: I18n.t('settings.activity_lightly_desc'),
        multiplier: 'x1.20',
      },
      {
        value: 'moderately_active',
        label: I18n.t('bmr.activity_moderately'),
        desc: I18n.t('settings.activity_moderately_desc'),
        multiplier: 'x1.35',
      },
      {
        value: 'strength_training',
        label: I18n.t('bmr.activity_strength'),
        desc: I18n.t('settings.activity_strength_desc'),
        multiplier: 'x1.50',
      },
    ];
  },

  _profileActivityLevel() {
    return (this._bmr && this._bmr.profile_activity_level)
      || (this._activity && this._activity.default_activity)
      || (this._bmr && this._bmr.activity_level)
      || 'lightly_active';
  },

  _activityLabel(level) {
    const key = {
      sedentary: 'bmr.activity_sedentary',
      lightly_active: 'bmr.activity_lightly',
      moderately_active: 'bmr.activity_moderately',
      strength_training: 'bmr.activity_strength',
    }[level];
    return key ? I18n.t(key) : I18n.t('home.summary_no_activity');
  },

  _activitySourceLabel(activity) {
    if (!activity) return I18n.t('settings.activity_source_unknown');
    if (activity.is_logged) return I18n.t('settings.activity_source_today');
    return I18n.t('settings.activity_source_default');
  },

  _goalLabel(goal) {
    const key = {
      improve_health: 'bmr.goal_improve_health',
      body_recomp: 'bmr.goal_body_recomp',
      fat_loss_slow: 'bmr.goal_fat_loss_slow',
      fat_loss_moderate: 'bmr.goal_fat_loss_moderate',
      fat_loss_fast: 'bmr.goal_fat_loss_fast',
      muscle_gain_slow: 'bmr.goal_muscle_gain_slow',
      muscle_gain_moderate: 'bmr.goal_muscle_gain_moderate',
      muscle_gain_fast: 'bmr.goal_muscle_gain_fast',
      lose: 'bmr.goal_lose',
      maintain: 'bmr.goal_maintain',
      gain: 'bmr.goal_gain',
    }[goal];
    return key ? I18n.t(key) : '--';
  },

  _membershipLabel(level) {
    return I18n.t(`membership.${level || 'free'}`);
  },

  _avatarText(user) {
    const source = user.username || user.email || 'C';
    return source.trim().slice(0, 1).toUpperCase();
  },

  _formatKg(value) {
    if (value === null || value === undefined || value === '') return '--';
    return `${this._formatNumber(value, 1)} ${I18n.t('common.kg')}`;
  },

  _formatKcal(value) {
    if (value === null || value === undefined || value === '') return '--';
    return `${this._formatNumber(value)} ${I18n.t('common.kcal')}`;
  },

  _formatNumber(value, fractionDigits = 0) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '--';
    return new Intl.NumberFormat(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', {
      maximumFractionDigits: fractionDigits,
      minimumFractionDigits: fractionDigits,
    }).format(numeric);
  },

  _showFieldError(el, message) {
    if (!el) return;
    el.textContent = message;
    el.classList.add('visible');
  },

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};
