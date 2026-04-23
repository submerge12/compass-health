/* ============================================================
   Compass Health - pages/meal_engine.js
   Fat-loss meal-planning UI (customer-facing tabs only)

   Flow:
     1. Meal Plan - breakfast/main dish pool, then arrange a week.
     2. Saved Recipes - personal library manager (up to tier cap).
     3. Shopping List - aggregate procurement.
     4. Feedback Loop - today + weekly review.
   ============================================================ */

const MealEnginePage = {
  _cache: {
    meal_plan_pool: null,
    pool_selection: null,
    arranged_plan: null,
    arrange_issue: null,
    pool_history: null,
    preference_catalog: null,
    saved: null,
    procurement: null,
    fixed_meals: null,
    daily: null,
    weekly: null,
  },
  _activeTab: 'meal_plan',
  _POOL_HISTORY_STORAGE_KEY: 'ch_meal_plan_pool_history_v1',
  _POOL_HISTORY_LIMIT: 3,

  _WEEKDAY_I18N: [
    'plan.weekday_mon', 'plan.weekday_tue', 'plan.weekday_wed',
    'plan.weekday_thu', 'plan.weekday_fri', 'plan.weekday_sat',
    'plan.weekday_sun',
  ],

  _weekdayLabel(wd) {
    if (wd == null) return I18n.t('plan.weekday_any');
    return I18n.t(this._WEEKDAY_I18N[wd] || 'plan.weekday_any');
  },

  _ACTIVITY_I18N: {
    sedentary:         'bmr.activity_sedentary',
    lightly_active:    'bmr.activity_lightly',
    moderately_active: 'bmr.activity_moderately',
    strength_training: 'bmr.activity_strength',
  },

  _activityLabel(slug) {
    const key = this._ACTIVITY_I18N[slug];
    if (!key) return slug;
    return I18n.t(key).replace(/\s*[（(]x[^)）]*[)）]\s*$/i, '').trim();
  },

  async render() {
    const el = document.getElementById('page-plan');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div>
          <h2>${t('plan.title')}</h2>
          <div class="subtitle">${t('plan.subtitle')}</div>
        </div>
      </div>

      <div class="plan-tabs" role="tablist">
        ${this._tabBtn('meal_plan',     'plan.tab_meal_plan')}
        ${this._tabBtn('fixed_meals',   'plan.tab_fixed_meals')}
        ${this._tabBtn('saved_recipes', 'plan.tab_saved_recipes')}
        ${this._tabBtn('procurement',   'plan.tab_procurement')}
        ${this._tabBtn('feedback',      'plan.tab_feedback')}
      </div>

      <div id="plan-panel"></div>
    `;

    el.querySelectorAll('.plan-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = btn.getAttribute('data-tab');
        el.querySelectorAll('.plan-tab').forEach(b =>
          b.classList.toggle('active', b === btn)
        );
        this._renderActive();
      });
    });

    this._renderActive();
  },

  _tabBtn(key, i18n) {
    const active = this._activeTab === key ? 'active' : '';
    return `<button type="button" class="plan-tab ${active}" data-tab="${key}">${I18n.t(i18n)}</button>`;
  },

  async _renderActive() {
    const panel = document.getElementById('plan-panel');
    if (!panel) return;
    panel.innerHTML = `<div class="card"><div class="loading-state"><span class="spinner"></span> ${I18n.t('common.loading')}</div></div>`;
    try {
      switch (this._activeTab) {
        case 'meal_plan':     await this._renderMealPlan(panel); break;
        case 'fixed_meals':   await this._renderFixedMeals(panel); break;
        case 'saved_recipes': await this._renderSavedRecipes(panel); break;
        case 'procurement':   await this._renderProcurement(panel); break;
        case 'feedback':      await this._renderFeedback(panel); break;
      }
      I18n.apply();
    } catch (err) {
      panel.innerHTML = `<div class="card"><div class="empty-state">${I18n.t('common.error')}: ${this._esc(err.message)}</div></div>`;
    }
  },

  /* Shared recipe render helpers */
  _renderIngredients(ings) {
    if (!ings) return `<div class="muted">--</div>`;
    if (typeof ings === 'string') {
      const lines = ings.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      if (!lines.length) return `<div class="muted">--</div>`;
      return `<ul class="plan-list">${lines.map(l => `<li>${this._esc(l)}</li>`).join('')}</ul>`;
    }
    if (!Array.isArray(ings) || !ings.length) return `<div class="muted">--</div>`;
    return `<ul class="plan-list">${ings.map(i => `<li>${this._esc(this._foodDisplayName(i))} · ${i.grams ?? 0}g</li>`).join('')}</ul>`;
  },

  _renderSeasonings(seasonings) {
    if (!Array.isArray(seasonings) || !seasonings.length) return '';
    return `<ul class="plan-list">${seasonings.map(s => `<li>${this._esc(this._foodDisplayName(s))} · ${s.grams ?? 0}g</li>`).join('')}</ul>`;
  },

  _renderSteps(method) {
    if (!method) return `<div class="muted">--</div>`;
    if (Array.isArray(method)) {
      return `<ol class="plan-list">${method.map(s => `<li>${this._esc(s)}</li>`).join('')}</ol>`;
    }
    const lines = String(method).split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (!lines.length) return `<div class="muted">--</div>`;
    return `<ol class="plan-list">${lines.map(l => `<li>${this._esc(l.replace(/^\d+\.\s*/, ''))}</li>`).join('')}</ol>`;
  },
  /* ------------------------------------------------------------------
     Tab - Saved Recipes
     ------------------------------------------------------------------ */
  async _renderSavedRecipes(panel) {
    const data = await API.listSavedRecipes();
    this._cache.saved = data;
    const t = k => I18n.t(k);

    const cap = data.cap == null ? '--' : data.cap;
    const items = (data.items || []).map(row => {
      const r = row.recipe || {};
      const savedAt = row.saved_at ? this._formatTime(row.saved_at) : '';
      return `
        <div class="card saved-recipe-card">
          <div class="flex-row">
            <div>
              <strong>${this._esc(r.name || '')}</strong>
              <div class="muted">${this._macroSummary({ kcal: r.calories, protein_g: r.protein_g, carbs_g: r.carbs_g, fat_g: r.fat_g })}</div>
              ${r.meal_types ? `<div class="muted">${t('plan.meal_types')}: ${this._esc(r.meal_types)}</div>` : ''}
              <div class="muted">${t('plan.saved_at')}: ${this._esc(savedAt)}</div>
            </div>
            <button type="button" class="btn btn-sm" data-saved-delete="${r.id}">${t('common.delete')}</button>
          </div>
          ${r.ingredients ? `<details><summary>${t('plan.recipe_ingredients')}</summary>${this._renderIngredients(r.ingredients)}</details>` : ''}
          ${r.steps ? `<details><summary>${t('plan.recipe_method')}</summary>${this._renderSteps(r.steps)}</details>` : ''}
        </div>`;
    }).join('');

    panel.innerHTML = `
      <div class="card">
        <h3>${t('plan.saved_recipes_title')}</h3>
        <div class="muted">${t('plan.saved_library_status').replace('{c}', data.count).replace('{cap}', cap)}</div>
      </div>
      ${items || `<div class="card muted">${t('plan.saved_empty')}</div>`}
    `;

    panel.querySelectorAll('[data-saved-delete]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm(I18n.t('common.confirm_delete'))) return;
        const id = btn.getAttribute('data-saved-delete');
        btn.disabled = true;
        try {
          await API.deleteSavedRecipe(id);
          await this._renderSavedRecipes(panel);
          I18n.apply();
        } catch (err) {
          btn.disabled = false;
          alert(`${I18n.t('common.error')}: ${err.message}`);
        }
      });
    });
  },

  /* ------------------------------------------------------------------
     Tab - Shopping list (procurement, spec-v1)
     ------------------------------------------------------------------ */
  async _renderProcurement(panel) {
    const data = await API.mealEngineProcurement(null);
    this._cache.procurement = data;
    const t = k => I18n.t(k);
    const lang = I18n.lang;

    if (data.feasibility === 'not_closed_loop') {
      panel.innerHTML = `<div class="card"><div class="empty-state">${this._esc(data[`message_${lang}`] || '')}</div></div>`;
      return;
    }

    const totalLine = t('plan.procurement_total')
      .replace('{n}', data.total_slugs || 0)
      .replace('{g}', data.total_planned_g || 0);

    const warnings = data.warnings || [];
    const warningsHtml = warnings.length ? `
      <div class="card">
        <h4>${t('plan.procurement_warnings_title')}</h4>
        <ul class="plan-list">${warnings.map(w => `<li>${this._esc(w)}</li>`).join('')}</ul>
        <div class="muted">${t('plan.pick_recipe_cta')}</div>
      </div>` : '';

    const groupsHtml = (data.groups || []).map(g => {
      const rows = g.rows.map(r => {
        const keyBadge = r.is_key_food
          ? `<span class="pill warn" title="${this._esc(t('plan.key_food_tip'))}">${t('plan.key_food')}</span>`
          : '';
        const replaceableBadge = r.replaceable
          ? `<span class="pill" title="${this._esc(t('plan.replaceable_tip'))}">${t('plan.replaceable_yes')}</span>`
          : '';
        return `
          <tr>
            <td>
              <strong>${this._esc(r[`name_${lang}`] || r.slug)}</strong>
              ${keyBadge} ${replaceableBadge}
              <div class="muted">${t('plan.meals_count').replace('{n}', r.meal_count)}</div>
            </td>
            <td>${r.planned_g} g</td>
            <td class="strong">${r.recommended_g} g</td>
          </tr>`;
      }).join('');
      return `
        <div class="card">
          <h3>${this._esc(g[`label_${lang}`])}</h3>
          <table class="plan-table">
            <thead><tr>
              <th>${t('plan.food')}</th>
              <th>${t('plan.planned_g')}</th>
              <th>${t('plan.recommended_g')}</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    }).join('');

    panel.innerHTML = `
      <div class="card">
        <h3>${t('plan.procurement_title')}</h3>
        <div class="muted">${this._esc(totalLine)}</div>
      </div>
      ${warningsHtml}
      ${groupsHtml || `<div class="card muted">${t('plan.no_procurement')}</div>`}
    `;
  },

  /* ------------------------------------------------------------------
     Tab - Fixed Meals (spec-v1 CRUD)
     ------------------------------------------------------------------ */
  async _renderFixedMeals(panel) {
    // Fetch the user's fixed meals and saved recipes in parallel.
    // The recipe picker in the add/edit form pulls from saved recipes.
    const [fixedRes, savedRes] = await Promise.all([
      API.listFixedMeals(),
      API.listSavedRecipes().catch(() => ({ items: [] })),
    ]);
    this._cache.fixed_meals = fixedRes;
    const t = k => I18n.t(k);

    const items = fixedRes.items || [];
    const savedRecipes = (savedRes.items || [])
      .map(row => row.recipe)
      .filter(Boolean);

    const rowsHtml = items.map(item => {
      const nameLabel = item.recipe_name || item.custom_name || '--';
      const portion = item.portion_g != null ? `${item.portion_g} g` : '--';
      return `
        <div class="card saved-recipe-card" data-fixed-row="${item.id}">
          <div class="flex-row">
            <div>
              <strong>${this._esc(nameLabel)}</strong>
              <div class="muted">
                ${this._esc(this._pairSummary([
                  this._weekdayLabel(item.weekday),
                  t('plan.meal_' + item.meal_type),
                  portion,
                ]))}
              </div>
              <div class="muted">${this._macroSummary({ kcal: item.calories, protein_g: item.protein_g, carbs_g: item.carbs_g, fat_g: item.fat_g })}</div>
            </div>
            <div>
              <button type="button" class="btn btn-sm" data-fixed-edit="${item.id}">${t('plan.fixed_edit_btn')}</button>
              <button type="button" class="btn btn-sm" data-fixed-delete="${item.id}">${t('common.delete')}</button>
            </div>
          </div>
        </div>`;
    }).join('');

    panel.innerHTML = `
      <div class="card">
        <div class="flex-row">
          <div>
            <h3>${t('plan.fixed_meals_title')}</h3>
            <div class="muted">${t('plan.fixed_meals_intro')}</div>
          </div>
          <button type="button" class="btn btn-primary btn-sm" id="fixed-add-btn">${t('plan.fixed_add_btn')}</button>
        </div>
      </div>
      ${rowsHtml || `<div class="card muted">${t('plan.fixed_meals_empty')}</div>`}
    `;

    document.getElementById('fixed-add-btn').addEventListener('click', () => {
      this._openFixedMealForm(null, savedRecipes, panel);
    });
    panel.querySelectorAll('[data-fixed-edit]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = Number(btn.getAttribute('data-fixed-edit'));
        const item = items.find(r => r.id === id);
        if (item) this._openFixedMealForm(item, savedRecipes, panel);
      });
    });
    panel.querySelectorAll('[data-fixed-delete]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm(I18n.t('common.confirm_delete'))) return;
        const id = Number(btn.getAttribute('data-fixed-delete'));
        btn.disabled = true;
        try {
          await API.deleteFixedMeal(id);
          await this._renderFixedMeals(panel);
          I18n.apply();
        } catch (err) {
          btn.disabled = false;
          alert(`${I18n.t('common.error')}: ${err.message}`);
        }
      });
    });
  },

  _openFixedMealForm(existing, savedRecipes, panel) {
    const t = k => I18n.t(k);
    const isEdit = !!existing;
    const title = t(isEdit ? 'plan.fixed_meal_edit_title' : 'plan.fixed_meal_new_title');

    const weekdayOptions = [
      { value: '', label: t('plan.weekday_any') },
      ...this._WEEKDAY_I18N.map((k, i) => ({ value: String(i), label: t(k) })),
    ].map(o => {
      const selected = existing && (existing.weekday === null ? o.value === '' : String(existing.weekday) === o.value);
      return `<option value="${o.value}" ${selected ? 'selected' : ''}>${this._esc(o.label)}</option>`;
    }).join('');

    const mealOptions = ['breakfast', 'lunch', 'dinner', 'snack'].map(mt => {
      const selected = existing && existing.meal_type === mt ? 'selected' : '';
      return `<option value="${mt}" ${selected}>${this._esc(t('plan.meal_' + mt))}</option>`;
    }).join('');

    const recipeOptions = [
      `<option value="">${this._esc(t('plan.fixed_form_recipe_none'))}</option>`,
      ...savedRecipes.map(r => {
        const selected = existing && existing.recipe_id === r.id ? 'selected' : '';
        return `<option value="${r.id}" ${selected}>${this._esc(r.name)}</option>`;
      }),
    ].join('');

    const body = `
      <form id="fixed-meal-form" onsubmit="return false;">
        <div class="form-group">
          <label>${t('plan.fixed_form_meal_type')}</label>
          <select name="meal_type" class="form-control" required>${mealOptions}</select>
        </div>
        <div class="form-group">
          <label>${t('plan.fixed_form_weekday')}</label>
          <select name="weekday" class="form-control">${weekdayOptions}</select>
        </div>
        <div class="form-group">
          <label>${t('plan.fixed_form_recipe')}</label>
          <select name="recipe_id" class="form-control">${recipeOptions}</select>
        </div>
        <div class="form-group">
          <label>${t('plan.fixed_form_portion')}</label>
          <input type="number" name="portion_g" class="form-control" step="1" min="1"
                 value="${existing && existing.portion_g != null ? existing.portion_g : ''}">
          <div class="form-hint">${t('plan.fixed_form_portion_hint')}</div>
        </div>
        <div class="form-group">
          <label>${t('plan.fixed_form_custom_name')}</label>
          <input type="text" name="custom_name" class="form-control"
                 value="${this._esc(existing?.custom_name || '')}">
          <div class="form-hint">${t('plan.fixed_form_custom_hint')}</div>
        </div>
        <div id="fixed-meal-form-error" class="form-error" style="display:none"></div>
      </form>
    `;

    const footer = `
      <button type="button" class="btn" id="fixed-cancel">${t('common.cancel')}</button>
      <button type="button" class="btn btn-primary" id="fixed-save">${t('common.save')}</button>
    `;

    App.openModal(title, body, footer);

    document.getElementById('fixed-cancel').addEventListener('click', () => App.closeModal());

    document.getElementById('fixed-save').addEventListener('click', async () => {
      const form = document.getElementById('fixed-meal-form');
      const data = new FormData(form);
      const payload = {
        meal_type: data.get('meal_type'),
        weekday: data.get('weekday') === '' ? null : Number(data.get('weekday')),
        recipe_id: data.get('recipe_id') ? Number(data.get('recipe_id')) : null,
        custom_name: (data.get('custom_name') || '').trim() || null,
        portion_g: data.get('portion_g') ? Number(data.get('portion_g')) : null,
      };

      const errEl = document.getElementById('fixed-meal-form-error');
      errEl.style.display = 'none';

      try {
        if (isEdit) {
          await API.updateFixedMeal(existing.id, payload);
        } else {
          await API.createFixedMeal(payload);
        }
        App.closeModal();
        await this._renderFixedMeals(panel);
        I18n.apply();
        App.showToast(I18n.t('common.success'), 'success');
      } catch (err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
      }
    });
  },

  /* ------------------------------------------------------------------
     Tab - Feedback (today + weekly)
     ------------------------------------------------------------------ */
  async _renderFeedback(panel) {
    const [daily, weekly] = await Promise.all([
      API.mealEngineDaily(),
      API.mealEngineWeekly(),
    ]);
    this._cache.daily = daily; this._cache.weekly = weekly;
    const t = k => I18n.t(k);
    const lang = I18n.lang;

    if (!daily.has_bmr_profile) {
      panel.innerHTML = `<div class="card"><div class="empty-state">${t('plan.no_bmr')}</div></div>`;
      return;
    }

    const statusBadge = (s) => ({
      on_track: `<span class="pill ok">${t('plan.on_track')}</span>`,
      under:    `<span class="pill warn">${t('plan.under')}</span>`,
      over:     `<span class="pill bad">${t('plan.over')}</span>`,
    }[s] || '');

    const pct = r => `${Math.round((r || 0) * 100)}%`;
    const dailyNotes = (daily.notes || []).map(n => `<li>${this._esc(n)}</li>`).join('');
    const weeklyAdj = (weekly.adjustments || []).map(a => {
      const cls = { calorie_up: 'warn', calorie_down: 'warn', protein_up: 'warn', carb_trim: 'warn' }[a.kind] || 'warn';
      return `<div class="suggestion-card ${cls}">${this._esc(a[`message_${lang}`])}</div>`;
    }).join('') || `<div class="muted">${t('plan.no_adjustments')}</div>`;

    panel.innerHTML = `
      <div class="card">
        <h3>${t('plan.today_report')} · ${daily.date}</h3>
        <table class="plan-table">
          <thead>
            <tr><th>${t('plan.metric')}</th><th>${t('plan.target')}</th><th>${t('plan.actual')}</th><th>${t('plan.achievement')}</th><th>${t('plan.status')}</th></tr>
          </thead>
          <tbody>
            <tr><td>${t('plan.kcal')}</td>    <td>${daily.target.kcal}</td>    <td>${daily.actual.kcal}</td>    <td>${pct(daily.achievement_rate.kcal)}</td>    <td>${statusBadge(daily.status.kcal)}</td></tr>
            <tr><td>${t('plan.protein')}</td> <td>${daily.target.protein_g} g</td><td>${daily.actual.protein_g} g</td><td>${pct(daily.achievement_rate.protein)}</td><td>${statusBadge(daily.status.protein)}</td></tr>
            <tr><td>${t('plan.carbs')}</td>   <td>${daily.target.carbs_g} g</td>  <td>${daily.actual.carbs_g} g</td>  <td>${pct(daily.achievement_rate.carbs)}</td>  <td>${statusBadge(daily.status.carbs)}</td></tr>
            <tr><td>${t('plan.fat')}</td>     <td>${daily.target.fat_g} g</td>    <td>${daily.actual.fat_g} g</td>    <td>${pct(daily.achievement_rate.fat)}</td>    <td>${statusBadge(daily.status.fat)}</td></tr>
          </tbody>
        </table>
        <div class="muted">${t('plan.exercise_kcal')}: ${daily.exercise_kcal} · ${t('plan.net_kcal')}: ${daily.net_kcal}</div>
        ${dailyNotes ? `<ul class="plan-list">${dailyNotes}</ul>` : ''}
      </div>

      <div class="card">
        <h3>${t('plan.weekly_review')}</h3>
        ${weekly.has_bmr_profile && weekly.averages ? `
          <div class="targets-grid">
            <div class="target-tile"><div class="label">${t('plan.kcal_avg')}</div><div class="value">${weekly.averages.kcal}</div></div>
            <div class="target-tile"><div class="label">${t('plan.protein_avg')}</div><div class="value">${weekly.averages.protein_g} g</div></div>
            <div class="target-tile"><div class="label">${t('plan.kcal_ach')}</div><div class="value">${pct(weekly.averages.kcal_achievement)}</div></div>
            <div class="target-tile"><div class="label">${t('plan.protein_ach')}</div><div class="value">${pct(weekly.averages.protein_achievement)}</div></div>
            <div class="target-tile"><div class="label">${t('plan.weight_trend')}</div><div class="value">${weekly.weight_trend_kg == null ? '--' : (weekly.weight_trend_kg > 0 ? '+' : '') + weekly.weight_trend_kg + ' kg'}</div></div>
          </div>` : `<div class="muted">${weekly[`message_${lang}`] || t('plan.no_weekly_data')}</div>`}
        <h4>${t('plan.adjustments')}</h4>
        ${weeklyAdj}
      </div>
    `;
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Helpers
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  /** Parse a "YYYY-MM-DD" into a 0=Monday..6=Sunday index, matching the
   *  backend's `UserFixedMeal.weekday` convention. JS Date.getDay()
   *  returns Sunday=0, so we shift. */
  _weekdayIndex(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    const js = new Date(y, m - 1, d).getDay();  // 0=Sun..6=Sat
    return (js + 6) % 7;                        // 鈫?0=Mon..6=Sun
  },
  _formatTime(iso) {
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleString(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
    } catch { return iso; }
  },
};

MealEnginePage._looksMojibake = function(value) {
  const text = String(value || '').trim();
  if (!text) return false;
  return /[�]|鈥|锛|闈|鎷|鏃|瀹|闁|瑜|鏉|杩|鏈|鍊欓|缃戠粶|閿欒/.test(text);
};

MealEnginePage._humanizeSlug = function(slug) {
  const raw = String(slug || '').trim();
  if (!raw) return '';
  return raw
    .split(/[_-]+/)
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
};

MealEnginePage._foodDisplayName = function(item) {
  if (!item) return '';
  const clean = value => {
    const text = String(value || '').trim();
    return text && !this._looksMojibake(text) ? text : '';
  };
  const zh = clean(item.name_zh);
  const en = clean(item.name_en);
  const name = clean(item.name);
  const slug = String(item.slug || '').trim();
  if (I18n.lang === 'zh') return zh || name || en || this._humanizeSlug(slug) || slug;
  return en || name || zh || this._humanizeSlug(slug) || slug;
};

MealEnginePage._macroSummary = function(totals) {
  return `${totals?.kcal ?? totals?.calories ?? '?'} kcal · P ${totals?.protein_g ?? '?'}g · C ${totals?.carbs_g ?? '?'}g · F ${totals?.fat_g ?? '?'}g`;
};

MealEnginePage._pairSummary = function(parts) {
  return parts.map(part => String(part || '').trim()).filter(Boolean).join(' · ');
};

MealEnginePage._userFacingMessage = function(value) {
  if (!value) return '';
  if (typeof value === 'object') {
    return value[`message_${I18n.lang}`]
      || value.message_zh
      || value.message_en
      || value.message
      || value.error
      || '';
  }
  const text = String(value).trim();
  if (!text) return '';
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      return this._userFacingMessage(JSON.parse(text)) || text;
    } catch {
      return text;
    }
  }
  return text;
};

MealEnginePage._normalizePoolDish = function(dish, fallbackMealType) {
  const rawIngredients = Array.isArray(dish.ingredients)
    ? dish.ingredients
    : Array.isArray(dish.parts)
      ? dish.parts.map(part => ({
          slug: part.slug,
          grams: part.grams,
          name: part.name_zh || part.name_en || part.slug,
          name_zh: part.name_zh,
          name_en: part.name_en,
        }))
      : [];
  const ingredients = rawIngredients
    .filter(item => item && item.slug)
    .map(item => ({
      slug: item.slug,
      grams: Number(item.grams || 0),
      name_zh: item.name_zh || '',
      name_en: item.name_en || '',
      name: this._foodDisplayName(item),
    }));
  const mealType = dish.meal_type === 'main' || fallbackMealType === 'main' ? 'main' : 'breakfast';
  const methodSteps = Array.isArray(dish.method_steps)
    ? dish.method_steps.join('\n')
    : String(dish.method_steps || '');
  const totals = dish.totals || {};
  const displayName = this._foodDisplayName({
    name: dish.name,
    name_zh: dish.name_zh,
    name_en: dish.name_en,
    slug: dish.slug,
  });
  return {
    dish_id: String(dish.dish_id ?? dish.sketch_id ?? `${mealType}-${ingredients.map(i => i.slug).join('-')}`),
    meal_type: mealType,
    name: String(displayName || this._sketchDishName(ingredients, mealType)),
    ingredients,
    totals: {
      kcal: Number(totals.kcal ?? 0),
      protein_g: Number(totals.protein_g ?? 0),
      carbs_g: Number(totals.carbs_g ?? 0),
      fat_g: Number(totals.fat_g ?? 0),
    },
    ingredient_slugs: Array.isArray(dish.ingredient_slugs)
      ? dish.ingredient_slugs.slice()
      : ingredients.map(item => item.slug),
    day_type_affinities: Array.isArray(dish.day_type_affinities) ? dish.day_type_affinities.slice() : [],
    method_steps: methodSteps,
    seasonings: Array.isArray(dish.seasonings) ? dish.seasonings.slice() : [],
  };
};

MealEnginePage._sketchDishName = function(ingredients, mealType) {
  const names = ingredients.slice(0, 3).map(item => String(item.name || item.slug || '').trim()).filter(Boolean);
  if (!names.length) return mealType === 'main' ? I18n.t('plan.pool_main_fallback_name') : I18n.t('plan.pool_breakfast_fallback_name');
  if (I18n.lang === 'en') {
    return `${names.join(' + ')} ${mealType === 'main' ? 'plate' : 'breakfast'}`;
  }
  return `${names.join(' + ')}${mealType === 'main' ? '拼盘' : '早餐'}`;
};

MealEnginePage._normalizePoolPayload = function(data, { namedWithLLM = false, source = 'named' } = {}) {
  const breakfastSource = data.breakfast_dishes || data.breakfast_pool || [];
  const mainSource = data.main_dishes || data.main_pool || [];
  const breakfastDishes = breakfastSource.map(dish => this._normalizePoolDish(dish, 'breakfast'));
  const mainDishes = mainSource.map(dish => this._normalizePoolDish(dish, 'main'));
  const startDate = data.start_date || data.week_skeleton?.[0]?.date || '';
  return {
    pool_tag: `${source}:${startDate}:${breakfastDishes.map(d => d.dish_id).join('|')}:${mainDishes.map(d => d.dish_id).join('|')}`,
    named_with_llm: namedWithLLM,
    source,
    start_date: startDate,
    breakfast_dishes: breakfastDishes,
    main_dishes: mainDishes,
    week_skeleton: Array.isArray(data.week_skeleton) ? data.week_skeleton.slice() : [],
    required_slot_counts: data.required_slot_counts || {},
    requires_breakfast_pool: typeof data.requires_breakfast_pool === 'boolean'
      ? data.requires_breakfast_pool
      : Number(data.required_slot_counts?.breakfast ?? 0) > 0,
    requires_main_pool: typeof data.requires_main_pool === 'boolean'
      ? data.requires_main_pool
      : (Number(data.required_slot_counts?.lunch ?? 0) + Number(data.required_slot_counts?.dinner ?? 0)) > 0,
    llm_quota: data.llm_quota || null,
    warnings: Array.isArray(data.warnings) ? data.warnings.slice() : [],
  };
};

MealEnginePage._serializePoolSelection = function(selection, poolData) {
  return {
    pool_tag: poolData?.pool_tag || selection?.pool_tag || '',
    breakfast: Array.from(selection?.breakfast || []),
    main: Array.from(selection?.main || []),
  };
};

MealEnginePage._loadPoolHistory = function() {
  try {
    const raw = localStorage.getItem(this._POOL_HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(item => item && item.id && item.pool && item.pool.pool_tag);
  } catch {
    return [];
  }
};

MealEnginePage._savePoolHistory = function(history) {
  const trimmed = Array.isArray(history) ? history.slice(0, this._POOL_HISTORY_LIMIT) : [];
  localStorage.setItem(this._POOL_HISTORY_STORAGE_KEY, JSON.stringify(trimmed));
  this._cache.pool_history = trimmed;
};

MealEnginePage._archiveCurrentPool = function(reason = 'refresh') {
  const pool = this._cache.meal_plan_pool;
  if (!pool) return;

  const snapshot = {
    id: `${pool.pool_tag}:${Date.now()}`,
    reason,
    saved_at: new Date().toISOString(),
    pool,
    selection: this._serializePoolSelection(this._cache.pool_selection, pool),
    arranged_plan: this._cache.arranged_plan || null,
  };

  const history = this._loadPoolHistory()
    .filter(item => item?.pool?.pool_tag !== pool.pool_tag);
  history.unshift(snapshot);
  this._savePoolHistory(history);
};

MealEnginePage._restorePoolSnapshot = async function(snapshotId, panel) {
  const snapshot = this._loadPoolHistory().find(item => item.id === snapshotId);
  if (!snapshot?.pool) return;

  this._cache.meal_plan_pool = snapshot.pool;
  this._cache.pool_selection = {
    pool_tag: snapshot.selection?.pool_tag || snapshot.pool.pool_tag,
    breakfast: new Set(snapshot.selection?.breakfast || snapshot.pool.breakfast_dishes.map(dish => dish.dish_id)),
    main: new Set(snapshot.selection?.main || snapshot.pool.main_dishes.map(dish => dish.dish_id)),
  };
  this._cache.arranged_plan = snapshot.arranged_plan || null;
  this._cache.arrange_issue = null;

  await this._renderMealPlanFromCache(panel, snapshot.pool);
  I18n.apply();
};

MealEnginePage._deletePoolSnapshot = async function(snapshotId, panel, poolData) {
  const history = this._loadPoolHistory().filter(item => item.id !== snapshotId);
  this._savePoolHistory(history);
  await this._renderMealPlanFromCache(panel, poolData);
  I18n.apply();
};

MealEnginePage._renderPoolHistory = function() {
  const history = this._cache.pool_history || [];
  if (!history.length) return '';
  const t = k => I18n.t(k);
  const cards = history.map(item => {
    const pool = item.pool || {};
    const breakfastCount = Array.isArray(item.selection?.breakfast)
      ? item.selection.breakfast.length
      : (pool.breakfast_dishes || []).length;
    const mainCount = Array.isArray(item.selection?.main)
      ? item.selection.main.length
      : (pool.main_dishes || []).length;
    return `
      <div class="pool-history-item">
        <div>
          <strong>${this._esc(this._formatTime(item.saved_at))}</strong>
          <div class="muted">${t('plan.pool_history_counts').replace('{b}', breakfastCount).replace('{m}', mainCount)}</div>
        </div>
        <div class="pool-history-actions">
          <button type="button" class="btn btn-sm" data-pool-restore="${this._esc(item.id)}">${t('plan.pool_history_restore')}</button>
          <button type="button" class="btn btn-sm" data-pool-history-delete="${this._esc(item.id)}">${t('common.delete')}</button>
        </div>
      </div>`;
  }).join('');
  return `
    <div class="card">
      <div class="flex-row">
        <div>
          <h4>${t('plan.pool_history_title')}</h4>
          <div class="muted">${t('plan.pool_history_help')}</div>
        </div>
      </div>
      <div class="pool-history-list">${cards}</div>
    </div>`;
};

MealEnginePage._ensureMealPlanPool = async function() {
  if (this._cache.meal_plan_pool) return this._cache.meal_plan_pool;
  this._cache.pool_history = this._cache.pool_history || this._loadPoolHistory();

  let normalized;
  try {
    const named = await API.nameMealPlanPool();
    normalized = this._normalizePoolPayload(named, { namedWithLLM: true, source: 'named' });
  } catch (err) {
    const raw = await API.getMealPlanPool();
    normalized = this._normalizePoolPayload(raw, { namedWithLLM: false, source: 'sketch' });
    normalized.warnings.unshift(I18n.t('plan.pool_fallback_warning'));
    const warningMessage = this._userFacingMessage(err?.detail || err?.message);
    if (warningMessage) normalized.warnings.push(warningMessage);
  }

  this._cache.meal_plan_pool = normalized;
  this._cache.arranged_plan = this._cache.arranged_plan || null;
  this._initPoolSelection(normalized);
  return normalized;
};

MealEnginePage._initPoolSelection = function(poolData) {
  const current = this._cache.pool_selection;
  if (current && current.pool_tag === poolData.pool_tag) return;
  this._cache.pool_selection = {
    pool_tag: poolData.pool_tag,
    breakfast: new Set(poolData.breakfast_dishes.map(dish => dish.dish_id)),
    main: new Set(poolData.main_dishes.map(dish => dish.dish_id)),
  };
};

MealEnginePage._selectedCount = function(group) {
  const selection = this._cache.pool_selection || {};
  const set = selection[group];
  return set ? set.size : 0;
};

MealEnginePage._isDishSelected = function(group, dishId) {
  const selection = this._cache.pool_selection || {};
  return !!selection[group]?.has(dishId);
};

MealEnginePage._selectedDishes = function(group, dishes) {
  const selection = this._cache.pool_selection || {};
  const set = selection[group] || new Set();
  return dishes.filter(dish => set.has(dish.dish_id));
};

MealEnginePage._requiresBreakfastPool = function(poolData) {
  return !!poolData?.requires_breakfast_pool;
};

MealEnginePage._requiresMainPool = function(poolData) {
  return !!poolData?.requires_main_pool;
};

MealEnginePage._poolSelectionMessage = function(poolData) {
  const breakfastMissing = this._requiresBreakfastPool(poolData) && this._selectedCount('breakfast') <= 0;
  const mainMissing = this._requiresMainPool(poolData) && this._selectedCount('main') <= 0;
  if (breakfastMissing && mainMissing) return I18n.t('plan.pool_selection_required');
  if (breakfastMissing) return I18n.t('plan.pool_selection_required_breakfast');
  if (mainMissing) return I18n.t('plan.pool_selection_required_main');
  if (!this._requiresBreakfastPool(poolData) && !this._requiresMainPool(poolData)) {
    return I18n.t('plan.pool_arrange_no_selection_needed');
  }
  if (!this._requiresBreakfastPool(poolData)) return I18n.t('plan.pool_breakfast_optional_hint');
  if (!this._requiresMainPool(poolData)) return I18n.t('plan.pool_main_optional_hint');
  return I18n.t('plan.pool_arrange_hint');
};

MealEnginePage._updatePoolSummary = function(panel, poolData) {
  const breakfastCount = this._selectedCount('breakfast');
  const mainCount = this._selectedCount('main');
  const breakfastEl = panel.querySelector('[data-pool-breakfast-count]');
  const mainEl = panel.querySelector('[data-pool-main-count]');
  if (breakfastEl) breakfastEl.textContent = I18n.t('plan.pool_selected_breakfast').replace('{n}', breakfastCount);
  if (mainEl) mainEl.textContent = I18n.t('plan.pool_selected_main').replace('{n}', mainCount);
  const arrangeBtn = panel.querySelector('#mp-arrange');
  const canArrange = (!this._requiresBreakfastPool(poolData) || breakfastCount > 0)
    && (!this._requiresMainPool(poolData) || mainCount > 0);
  if (arrangeBtn) arrangeBtn.disabled = !canArrange;

  panel.querySelectorAll('[data-pool-select]').forEach(input => {
    const card = input.closest('.pool-dish-card');
    if (card) card.classList.toggle('selected', input.checked);
  });

  const hint = panel.querySelector('[data-pool-arrange-hint]');
  if (hint) {
    hint.textContent = this._poolSelectionMessage(poolData);
  }
};

MealEnginePage._refreshMealPlanPool = async function(panel, reason = 'refresh') {
  this._archiveCurrentPool(reason);
  this._cache.meal_plan_pool = null;
  this._cache.pool_selection = null;
  this._cache.arranged_plan = null;
  this._cache.arrange_issue = null;
  await this._renderMealPlan(panel);
  I18n.apply();
};

MealEnginePage._collectRecommendedFoods = function(missingMicronutrients = []) {
  const seen = new Map();
  missingMicronutrients.forEach(item => {
    (item.recommended_foods || []).forEach(food => {
      if (!food?.slug) return;
      if (!seen.has(food.slug)) {
        seen.set(food.slug, {
          slug: food.slug,
          name_zh: food.name_zh || food.slug,
          name_en: food.name_en || food.slug,
          roles: Array.isArray(food.roles) ? food.roles.slice() : [],
          role_labels_zh: Array.isArray(food.role_labels_zh) ? food.role_labels_zh.slice() : [],
          role_labels_en: Array.isArray(food.role_labels_en) ? food.role_labels_en.slice() : [],
        });
        return;
      }
      const current = seen.get(food.slug);
      (food.roles || []).forEach(role => {
        if (!current.roles.includes(role)) current.roles.push(role);
      });
      (food.role_labels_zh || []).forEach(label => {
        if (!current.role_labels_zh.includes(label)) current.role_labels_zh.push(label);
      });
      (food.role_labels_en || []).forEach(label => {
        if (!current.role_labels_en.includes(label)) current.role_labels_en.push(label);
      });
    });
  });
  return Array.from(seen.values());
};

MealEnginePage._normalizeArrangeIssue = function(detail) {
  const micronutrients = detail?.micronutrients || {};
  const missingMicronutrients = Array.isArray(detail?.missing_micronutrients) && detail.missing_micronutrients.length
    ? detail.missing_micronutrients.map(item => ({
        role: item.role,
        label_zh: item.label_zh || item.role,
        label_en: item.label_en || item.role,
        unit: item.unit || '',
        actual: Number(item.actual || 0),
        target: Number(item.target || 0),
        gap: Number(item.gap ?? Math.max(0, Number(item.target || 0) - Number(item.actual || 0))),
        carriers: Array.isArray(item.carriers) ? item.carriers.slice() : [],
        recommended_foods: Array.isArray(item.recommended_foods) ? item.recommended_foods.slice() : [],
      }))
    : Object.entries(micronutrients)
        .filter(([, info]) => info?.status === 'missing')
        .map(([role, info]) => ({
          role,
          label_zh: info.label_zh || role,
          label_en: info.label_en || role,
          unit: info.unit || '',
          actual: Number(info.actual || 0),
          target: Number(info.target || 0),
          gap: Math.max(0, Number(info.target || 0) - Number(info.actual || 0)),
          carriers: Array.isArray(info.carriers) ? info.carriers.slice() : [],
          recommended_foods: [],
        }));

  const recommendedFoods = Array.isArray(detail?.recommended_foods) && detail.recommended_foods.length
    ? detail.recommended_foods.map(food => ({
        slug: food.slug,
        name_zh: food.name_zh || food.slug,
        name_en: food.name_en || food.slug,
        roles: Array.isArray(food.roles) ? food.roles.slice() : [],
        role_labels_zh: Array.isArray(food.role_labels_zh) ? food.role_labels_zh.slice() : [],
        role_labels_en: Array.isArray(food.role_labels_en) ? food.role_labels_en.slice() : [],
      }))
    : this._collectRecommendedFoods(missingMicronutrients);

  return {
    error: detail?.error || 'weekly_micronutrients_missing',
    message_zh: detail?.message_zh || '',
    message_en: detail?.message_en || '',
    warnings: Array.isArray(detail?.warnings) ? detail.warnings.slice() : [],
    micronutrients,
    missing_micronutrients: missingMicronutrients,
    recommended_foods: recommendedFoods,
    added_slugs: [],
    action_message: '',
  };
};

MealEnginePage._getPreferenceCatalog = async function() {
  if (this._cache.preference_catalog) return this._cache.preference_catalog;
  const prefs = await API.getFoodPreferences();
  const slugToCategory = {};
  Object.entries(prefs.known || {}).forEach(([category, items]) => {
    (items || []).forEach(slug => {
      if (slug && !slugToCategory[slug]) slugToCategory[slug] = category;
    });
  });
  this._cache.preference_catalog = { known: prefs.known || {}, slugToCategory };
  return this._cache.preference_catalog;
};

MealEnginePage._addRecommendedFoodsToPreferences = async function(foods, { refreshPool = false, panel = null } = {}) {
  const catalog = await this._getPreferenceCatalog();
  const items = [];
  const skipped = [];

  foods.forEach(food => {
    const slug = typeof food === 'string' ? food : food?.slug;
    if (!slug) return;
    const category = catalog.slugToCategory[slug];
    if (!category) {
      skipped.push(slug);
      return;
    }
    items.push({ category, item_key: slug });
  });

  if (!items.length) {
    return { added: [], skipped };
  }

  await API.saveFoodPreferences(items, { replace: false });
  const added = items.map(item => item.item_key);
  if (refreshPool && panel) {
    await this._refreshMealPlanPool(panel, 'preferences_update');
  }
  return { added, skipped };
};

MealEnginePage._renderArrangeIssue = function(issue) {
  if (!issue || issue.error !== 'weekly_micronutrients_missing') return '';
  const t = k => I18n.t(k);
  const lang = I18n.lang;
  const missingRows = (issue.missing_micronutrients || []).map(item => `
    <div class="plan-issue-row">
      <div>
        <strong>${this._esc(item[`label_${lang}`] || item.label_en || item.role)}</strong>
        <div class="muted">${t('plan.issue_gap').replace('{a}', item.actual ?? 0).replace('{t}', item.target ?? 0).replace('{u}', item.unit || '')}</div>
      </div>
    </div>`).join('');

  const allAdded = (issue.recommended_foods || []).length > 0
    && issue.recommended_foods.every(food => (issue.added_slugs || []).includes(food.slug));
  const recommendationCards = (issue.recommended_foods || []).map(food => {
    const name = this._foodDisplayName(food);
    const roleLabels = (lang === 'zh' ? food.role_labels_zh : food.role_labels_en) || [];
    const added = (issue.added_slugs || []).includes(food.slug);
    return `
      <div class="plan-recommend-card">
        <div>
          <strong>${this._esc(name)}</strong>
          <div class="muted">${this._esc(roleLabels.join(lang === 'zh' ? '、' : ', '))}</div>
        </div>
        <button type="button" class="btn btn-sm" data-pref-add="${this._esc(food.slug)}" ${added ? 'disabled' : ''}>
          ${added ? t('plan.issue_added_notice') : t('plan.issue_add_pref_btn')}
        </button>
      </div>`;
  }).join('');

  return `
    <div class="card plan-issue-card">
      <div class="flex-row">
        <div>
          <h4>${t('plan.issue_title')}</h4>
          <div class="muted">${this._esc(issue[`message_${lang}`] || issue.message_en || '')}</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm" id="mp-add-all-pref-refresh" ${allAdded || !(issue.recommended_foods || []).length ? 'disabled' : ''}>
          ${t('plan.issue_add_all_and_refresh')}
        </button>
      </div>
      ${issue.action_message ? `<div class="plan-issue-feedback">${this._esc(issue.action_message)}</div>` : ''}
      <div class="plan-issue-grid">
        <div>
          <h5>${t('plan.issue_missing_list')}</h5>
          <div class="plan-issue-list">${missingRows}</div>
        </div>
        <div>
          <h5>${t('plan.issue_recommendations_title')}</h5>
          <div class="plan-recommend-grid">${recommendationCards || `<div class="muted">${t('plan.issue_no_supported_foods')}</div>`}</div>
        </div>
      </div>
    </div>`;
};

MealEnginePage._formatAffinityChips = function(dish) {
  const affinities = Array.isArray(dish.day_type_affinities) ? dish.day_type_affinities : [];
  return affinities.map(dayType => {
    const key = I18n.lang === 'zh' ? `day_type_label_zh` : `day_type_label_en`;
    const label = ({
      low_activity: I18n.t('plan.day_type_low_activity'),
      moderate_activity: I18n.t('plan.day_type_moderate_activity'),
      high_activity: I18n.t('plan.day_type_high_activity'),
      red_meat_day: I18n.t('plan.day_type_red_meat'),
      deep_sea_fish_day: I18n.t('plan.day_type_deep_sea_fish'),
      pantry_clearance: I18n.t('plan.day_type_pantry_clearance'),
    })[dayType] || key || dayType;
    return `<span class="food-chip">${this._esc(label)}</span>`;
  }).join('');
};

MealEnginePage._renderPoolDishCard = function(dish, group) {
  const checked = this._isDishSelected(group, dish.dish_id) ? 'checked' : '';
  const totals = dish.totals || {};
  const details = dish.method_steps || (dish.seasonings || []).length
    ? `<details class="pool-dish-details">
         <summary>${I18n.t('plan.pool_view_recipe')}</summary>
         <div class="drawer-section">
           <h4>${I18n.t('plan.recipe_ingredients')}</h4>
           ${this._renderIngredients(dish.ingredients)}
         </div>
         ${(dish.seasonings || []).length ? `<div class="drawer-section"><h4>${I18n.t('plan.recipe_seasonings')}</h4>${this._renderSeasonings(dish.seasonings)}</div>` : ''}
         ${dish.method_steps ? `<div class="drawer-section"><h4>${I18n.t('plan.recipe_method')}</h4>${this._renderSteps(dish.method_steps)}</div>` : ''}
       </details>`
    : `<div class="drawer-section"><h4>${I18n.t('plan.recipe_ingredients')}</h4>${this._renderIngredients(dish.ingredients)}</div>`;

  return `
    <div class="pool-dish-card ${checked ? 'selected' : ''}">
      <div class="pool-dish-head">
        <div class="pool-dish-check">
          <input type="checkbox" data-pool-select="${this._esc(group)}:${this._esc(dish.dish_id)}" ${checked}>
        </div>
        <div class="pool-dish-main">
          <div class="pool-dish-title">
            <strong>${this._esc(dish.name)}</strong>
            <span class="muted">${this._macroSummary(totals)}</span>
          </div>
          <div class="pool-chip-row">${this._formatAffinityChips(dish)}</div>
        </div>
      </div>
      ${details}
    </div>`;
};

MealEnginePage._renderWeekSkeleton = function(weekSkeleton) {
  if (!Array.isArray(weekSkeleton) || !weekSkeleton.length) return '';
  const lang = I18n.lang;
  const rows = weekSkeleton.map(day => {
    const label = day[`day_type_label_${lang}`] || day.day_type || '';
    const lockBadge = day.is_locked
      ? `<span class="pill warn">${I18n.t('plan.pool_day_locked')}</span>`
      : `<span class="pill">${I18n.t('plan.pool_day_flexible')}</span>`;
    return `<div class="pool-week-row"><strong>${this._esc(day.date)}</strong><span>${this._esc(label)}</span>${lockBadge}</div>`;
  }).join('');
  return `
    <div class="card">
      <h4>${I18n.t('plan.pool_week_skeleton')}</h4>
      <div class="pool-week-grid">${rows}</div>
    </div>`;
};

MealEnginePage._renderMicronutrientSummary = function(plan) {
  const rows = Object.entries(plan.micronutrients || {}).map(([, info]) => {
    const label = info[`label_${I18n.lang}`] || info.label_en || '';
    const pillCls = info.status === 'ok' ? 'ok' : (info.status === 'low' ? 'warn' : 'bad');
    return `<tr>
      <td>${this._esc(label)}</td>
      <td>${info.actual ?? 0} / ${info.target ?? 0} ${this._esc(info.unit || '')}</td>
      <td><span class="pill ${pillCls}">${this._esc(info.status)}</span></td>
    </tr>`;
  }).join('');
  if (!rows) return '';
  return `
    <div class="card">
      <h4>${I18n.t('plan.micronutrient_title')}</h4>
      <table class="plan-table">
        <thead><tr><th>${I18n.t('plan.nutrient')}</th><th>${I18n.t('plan.target')}</th><th>${I18n.t('plan.status')}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
};

MealEnginePage._renderArrangedWeek = function(plan) {
  if (!plan || !Array.isArray(plan.days) || !plan.days.length) return '';
  const t = k => I18n.t(k);
  const lang = I18n.lang;
  const warningHtml = (plan.warnings || []).length
    ? `<div class="card"><h4>${t('plan.warnings')}</h4><ul class="plan-list">${plan.warnings.map(w => `<li>${this._esc(this._userFacingMessage(w) || w)}</li>`).join('')}</ul></div>`
    : '';
  const dayCards = plan.days.map(day => {
    const mealBlocks = ['breakfast', 'lunch', 'dinner'].map(mt => {
      const meal = day.meals?.[mt];
      if (!meal) {
        return `<div class="meal-block"><div class="meal-head"><strong>${t('plan.meal_' + mt)}</strong><span class="muted">${t('plan.pool_unfilled_slot')}</span></div></div>`;
      }
      const totals = meal.totals || {};
      const pillCls = meal.source === 'selected' ? 'ok' : (meal.source === 'fixed' ? 'warn' : '');
      const details = (meal.ingredients || []).length || meal.method_steps
        ? `<details class="pool-dish-details">
             <summary>${t('plan.pool_view_recipe')}</summary>
             ${(meal.ingredients || []).length ? `<div class="drawer-section"><h4>${t('plan.recipe_ingredients')}</h4>${this._renderIngredients(meal.ingredients)}</div>` : ''}
             ${(meal.seasonings || []).length ? `<div class="drawer-section"><h4>${t('plan.recipe_seasonings')}</h4>${this._renderSeasonings(meal.seasonings)}</div>` : ''}
             ${meal.method_steps ? `<div class="drawer-section"><h4>${t('plan.recipe_method')}</h4>${this._renderSteps(meal.method_steps)}</div>` : ''}
           </details>`
        : '';
      return `
        <div class="meal-block">
          <div class="meal-head">
            <strong>${t('plan.meal_' + mt)}</strong>
            <span class="pill ${pillCls}">${this._esc(meal.source || '')}</span>
          </div>
          <div class="pool-arranged-name">${this._esc(meal.name || '')}</div>
          <div class="muted">${this._macroSummary(totals)}</div>
          ${details}
        </div>`;
    }).join('');
    return `
      <div class="day-card">
        <div class="day-card-head">
          <div>
            <strong>${this._esc(day.date)}</strong>
            <span class="day-type pill">${this._esc(day[`day_type_label_${lang}`] || day.day_type || '')}</span>
          </div>
          <div class="muted">${t('plan.target')}: ${day.target?.calorie_target ?? '?'} kcal · ${t('plan.actual')}: ${day.totals?.kcal ?? '?'} kcal</div>
        </div>
        ${mealBlocks}
      </div>`;
  }).join('');

  return `
    <div class="card">
      <div class="flex-row">
        <div>
          <h3>${t('plan.arranged_title')}</h3>
          <div class="muted">${t('plan.arranged_written').replace('{n}', plan.arranged_entry_count ?? 0)}</div>
        </div>
        <div class="muted">${t('plan.week_from').replace('{d}', plan.start_date || '')}</div>
      </div>
    </div>
    ${warningHtml}
    ${this._renderMicronutrientSummary(plan)}
    <div class="day-cards">${dayCards}</div>`;
};

MealEnginePage._renderMealPlanFromCache = async function(panel, poolData) {
  const t = k => I18n.t(k);
  this._cache.pool_history = this._loadPoolHistory();
  const quota = poolData.llm_quota || null;
  const quotaLine = quota
    ? t('plan.pool_quota_status')
        .replace('{r}', quota.remaining ?? 0)
        .replace('{l}', quota.limit ?? 0)
    : t(poolData.named_with_llm ? 'plan.pool_named_notice' : 'plan.pool_sketch_notice');
  const warningsHtml = (poolData.warnings || []).length
    ? `<div class="card"><h4>${t('plan.warnings')}</h4><ul class="plan-list">${poolData.warnings.map(w => `<li>${this._esc(this._userFacingMessage(w) || w)}</li>`).join('')}</ul></div>`
    : '';
  const historyHtml = this._renderPoolHistory();
  const breakfastCards = poolData.breakfast_dishes.map(dish => this._renderPoolDishCard(dish, 'breakfast')).join('');
  const mainCards = poolData.main_dishes.map(dish => this._renderPoolDishCard(dish, 'main')).join('');
  const issueHtml = this._cache.arrange_issue
    ? this._renderArrangeIssue(this._cache.arrange_issue)
    : '';
  const arrangedHtml = this._cache.arranged_plan
    ? this._renderArrangedWeek(this._cache.arranged_plan)
    : `<div class="card muted">${t('plan.pool_arrange_empty')}</div>`;

  panel.innerHTML = `
    <div class="card">
      <div class="flex-row">
        <div>
          <h3>${t('plan.meal_plan_title')}</h3>
          <div class="muted">${t('plan.pool_intro')}</div>
        </div>
        <div style="text-align:right">
          <button class="btn btn-primary btn-sm" id="mp-refresh-pool">${t('plan.pool_refresh_btn')}</button>
          <div class="muted" style="margin-top:4px">${this._esc(quotaLine)}</div>
        </div>
      </div>
      <div class="pool-selection-summary">
        <span class="pill ok" data-pool-breakfast-count></span>
        <span class="pill ok" data-pool-main-count></span>
      </div>
      <div class="muted" data-pool-arrange-hint>${t('plan.pool_arrange_hint')}</div>
    </div>
    ${warningsHtml}
    ${historyHtml}
    ${this._renderWeekSkeleton(poolData.week_skeleton)}
    <div class="card">
      <h4>${t('plan.pool_breakfast_section')}</h4>
      <div class="muted">${t('plan.pool_default_selected')}</div>
      <div class="pool-dish-grid">${breakfastCards || `<div class="muted">${t('plan.no_candidates')}</div>`}</div>
    </div>
    <div class="card">
      <h4>${t('plan.pool_main_section')}</h4>
      <div class="pool-dish-grid">${mainCards || `<div class="muted">${t('plan.no_candidates')}</div>`}</div>
    </div>
    <div class="card">
      <div class="flex-row">
        <div>
          <h4>${t('plan.arranged_title')}</h4>
          <div class="muted">${t('plan.pool_arrange_help')}</div>
        </div>
        <button class="btn btn-primary btn-sm" id="mp-arrange">${t('plan.pool_arrange_btn')}</button>
      </div>
    </div>
    ${issueHtml}
    ${arrangedHtml}
  `;

  this._updatePoolSummary(panel, poolData);

  document.getElementById('mp-refresh-pool')?.addEventListener('click', async () => {
    if (!confirm(t('plan.pool_refresh_confirm'))) return;
    await this._refreshMealPlanPool(panel, 'refresh');
  });

  panel.querySelectorAll('[data-pool-restore]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await this._restorePoolSnapshot(btn.getAttribute('data-pool-restore'), panel);
    });
  });

  panel.querySelectorAll('[data-pool-history-delete]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await this._deletePoolSnapshot(btn.getAttribute('data-pool-history-delete'), panel, poolData);
    });
  });

  panel.querySelectorAll('[data-pool-select]').forEach(input => {
    input.addEventListener('change', () => {
      const [group, ...dishIdParts] = String(input.getAttribute('data-pool-select') || '').split(':');
      const dishId = dishIdParts.join(':');
      const set = this._cache.pool_selection?.[group];
      if (!set) return;
      if (input.checked) set.add(dishId);
      else set.delete(dishId);
      this._updatePoolSummary(panel, poolData);
    });
  });

  document.getElementById('mp-arrange')?.addEventListener('click', async () => {
    const breakfast = this._selectedDishes('breakfast', poolData.breakfast_dishes);
    const main = this._selectedDishes('main', poolData.main_dishes);
    const breakfastMissing = this._requiresBreakfastPool(poolData) && !breakfast.length;
    const mainMissing = this._requiresMainPool(poolData) && !main.length;
    if (breakfastMissing || mainMissing) {
      alert(this._poolSelectionMessage(poolData));
      return;
    }

    const btn = document.getElementById('mp-arrange');
    if (btn) {
      btn.disabled = true;
      btn.textContent = t('common.loading');
    }
    try {
      const plan = await API.arrangeMealPlan({
        breakfast_dishes: breakfast,
        main_dishes: main,
      });
      this._cache.arrange_issue = null;
      this._cache.arranged_plan = plan;
      await this._renderMealPlanFromCache(panel, poolData);
      I18n.apply();
    } catch (err) {
      const detail = err.detail || {};
      if (detail.error === 'weekly_micronutrients_missing') {
        this._cache.arrange_issue = this._normalizeArrangeIssue(detail);
        await this._renderMealPlanFromCache(panel, poolData);
        I18n.apply();
      } else {
        const msg = detail[`message_${I18n.lang}`] || detail.message_en || err.message;
        alert(`${t('common.error')}: ${msg}`);
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = t('plan.pool_arrange_btn');
      }
    }
  });

  panel.querySelectorAll('[data-pref-add]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const slug = btn.getAttribute('data-pref-add');
      if (!slug || !this._cache.arrange_issue) return;
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = t('common.loading');
      try {
        const result = await this._addRecommendedFoodsToPreferences([slug], { panel, refreshPool: false });
        const addedSet = new Set(this._cache.arrange_issue.added_slugs || []);
        result.added.forEach(item => addedSet.add(item));
        this._cache.arrange_issue.added_slugs = Array.from(addedSet);
        this._cache.arrange_issue.action_message = result.skipped.length
          ? t('plan.issue_added_partial').replace('{n}', result.added.length).replace('{m}', result.skipped.length)
          : t('plan.issue_added_notice');
        await this._renderMealPlanFromCache(panel, poolData);
        I18n.apply();
      } catch (error) {
        btn.disabled = false;
        btn.textContent = originalText;
        alert(`${t('common.error')}: ${error.message}`);
      }
    });
  });

  document.getElementById('mp-add-all-pref-refresh')?.addEventListener('click', async () => {
    const issue = this._cache.arrange_issue;
    if (!issue) return;
    const btn = document.getElementById('mp-add-all-pref-refresh');
    const foods = (issue.recommended_foods || []).filter(food => !issue.added_slugs.includes(food.slug));
    if (!foods.length) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = t('common.loading');
    try {
      const result = await this._addRecommendedFoodsToPreferences(foods, { panel, refreshPool: true });
      if (!result.added.length && result.skipped.length) {
        this._cache.arrange_issue.action_message = t('plan.issue_no_supported_foods');
      }
    } catch (error) {
      btn.disabled = false;
      btn.textContent = originalText;
      alert(`${t('common.error')}: ${error.message}`);
    }
  });
};

MealEnginePage._renderMealPlan = async function(panel) {
  const poolData = await this._ensureMealPlanPool();
  await this._renderMealPlanFromCache(panel, poolData);
};
