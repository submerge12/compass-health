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
    pool_carryover: null,
    arranged_plan: null,
    arrange_issue: null,
    pool_history: null,
    pool_history_key: null,
    pool_variant: 0,
    pool_source_filter: 'all',
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

  _localizedRecipeName(name) {
    const raw = String(name || '').trim();
    if (!raw) return raw;
    const zh = {
      'fixed breakfast': '固定早餐',
      'breakfast': '早餐',
      '2 eggs + 200ml milk': '2个鸡蛋 + 200ml 牛奶',
      '2 eggs + 200 ml milk': '2个鸡蛋 + 200ml 牛奶',
    };
    const en = {
      '固定早餐': 'Fixed breakfast',
      '早餐': 'Breakfast',
      '2个鸡蛋 + 200ml 牛奶': '2 eggs + 200ml milk',
    };
    const key = raw.toLowerCase();
    if (I18n.lang === 'en') return en[raw] || raw;
    return zh[key] || raw;
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
        this._selectTab(btn.getAttribute('data-tab'));
        this._renderActive();
      });
    });

    this._renderActive();
  },

  _tabBtn(key, i18n) {
    const active = this._activeTab === key ? 'active' : '';
    return `<button type="button" class="plan-tab ${active}" data-tab="${key}">${I18n.t(i18n)}</button>`;
  },

  _selectTab(key) {
    this._activeTab = key;
    document.querySelectorAll('#page-plan .plan-tab').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === key);
    });
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
      const closedLoopIssue = this._normalizeClosedLoopIssue(err.detail || err.message);
      if (closedLoopIssue) {
        panel.innerHTML = this._renderClosedLoopIssue(closedLoopIssue);
        this._bindClosedLoopIssueActions(panel, closedLoopIssue);
        I18n.apply();
        return;
      }
      panel.innerHTML = `<div class="card"><div class="empty-state">${I18n.t('common.error')}: ${this._esc(this._userFacingMessage(err.detail || err.message) || err.message)}</div></div>`;
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
  async _renderProcurement(panel, preloadedData = null) {
    const data = preloadedData || await API.mealEngineProcurement(null);
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
      const nameLabel = this._localizedRecipeName(item.recipe_name || item.custom_name || '--');
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

MealEnginePage._renderWarningCard = function(warnings, title = I18n.t('plan.warnings')) {
  const items = this._formatPlanWarnings(warnings);
  if (!items.length) return '';
  return `
    <div class="card plan-warning-card">
      <h4>${this._esc(title)}</h4>
      <ul class="plan-list">${items.map(item => `<li>${this._esc(item)}</li>`).join('')}</ul>
    </div>
  `;
};

MealEnginePage._formatPlanWarnings = function(warnings) {
  if (!Array.isArray(warnings) || !warnings.length) return [];
  const kcalGaps = [];
  const output = [];
  warnings.forEach(warning => {
    const raw = String(warning || '').trim();
    if (!raw) return;
    const kcalMatch = raw.match(/^(\d{4}-\d{2}-\d{2}): daily kcal gap ([\d.]+) exceeds the preferred planning band\.?$/i);
    if (kcalMatch) {
      kcalGaps.push({ date: kcalMatch[1], gap: Number(kcalMatch[2]) });
      return;
    }
    output.push(this._translatePlanWarning(raw));
  });

  if (kcalGaps.length) {
    kcalGaps.sort((a, b) => a.date.localeCompare(b.date));
    const gapText = kcalGaps.map(item => {
      const gap = Number.isFinite(item.gap) ? Math.round(item.gap) : item.gap;
      return I18n.lang === 'zh'
        ? `${this._formatDateShort(item.date)} 差 ${gap} kcal`
        : `${this._formatDateShort(item.date)} off by ${gap} kcal`;
    }).join(I18n.lang === 'zh' ? '、' : ', ');
    output.unshift(I18n.lang === 'zh'
      ? `有 ${kcalGaps.length} 天热量偏离目标超过系统偏好范围：${gapText}。通常是固定餐/已记录餐占位、候选菜热量不够贴合，或保留的候选池太少；餐单仍可用，可按需手动替换。`
      : `${kcalGaps.length} days are outside the preferred calorie band: ${gapText}. This usually comes from fixed/logged meals, imperfect candidate calories, or too few kept candidates; the plan is still usable and can be adjusted manually.`);
  }

  return output;
};

MealEnginePage._translatePlanWarning = function(raw) {
  const microMatch = raw.match(/^weekly micronutrient coverage is low for (.+?) \(([\d.]+)\/([\d.]+) ([^)]+)\)\.?$/i);
  if (microMatch) {
    const nutrient = this._nutrientLabel(microMatch[1]);
    return I18n.lang === 'zh'
      ? `本周${nutrient}覆盖略低：${microMatch[2]}/${microMatch[3]} ${microMatch[4]}。差距不大时不会阻止排餐，可通过坚果、种子或健康脂肪类食材补足。`
      : `Weekly ${nutrient} coverage is slightly low: ${microMatch[2]}/${microMatch[3]} ${microMatch[4]}. This does not block the plan; add nuts, seeds, or healthy fats to cover it.`;
  }

  if (/some recorded meals do not expose structured ingredients/i.test(raw)) {
    return I18n.lang === 'zh'
      ? '有已记录餐食缺少结构化食材明细，系统可能低估本周微量元素覆盖；用“食材+重量”记录会更准确。'
      : 'Some logged meals do not include structured ingredient details, so weekly micronutrient coverage may be understated.';
  }

  const repetitionMatch = raw.match(/^high weekly repetition for:\s*(.+)$/i);
  if (repetitionMatch) {
    const names = repetitionMatch[1]
      .split(',')
      .map(slug => this._foodLabelForSlug(slug.trim()))
      .filter(Boolean)
      .join(I18n.lang === 'zh' ? '、' : ', ');
    return I18n.lang === 'zh'
      ? `本周重复食材偏多：${names}。这是因为这些食材更容易满足热量和营养目标；可以重新生成候选池，或取消一些重复菜。`
      : `High weekly ingredient repetition: ${names}. These foods fit the targets easily; regenerate the pool or deselect repeated dishes for more variety.`;
  }

  const floorMatch = raw.match(/^'([^']+)' placed ×(\d+) this week \(weekly_floor=(\d+)\)\. Consider scheduling it explicitly\.?$/i);
  if (floorMatch) {
    const name = this._foodLabelForSlug(floorMatch[1]);
    return I18n.lang === 'zh'
      ? `${name} 本周出现 ${floorMatch[2]} 次，低于建议 ${floorMatch[3]} 次；可以手动安排一次。`
      : `${name} appears ${floorMatch[2]} time(s), below the suggested ${floorMatch[3]}; schedule it manually if needed.`;
  }

  return this._userFacingMessage(raw) || raw;
};

MealEnginePage._foodLabelForSlug = function(slug) {
  const key = String(slug || '').trim();
  if (!key) return '';
  if (typeof PREF_LABELS !== 'undefined' && PREF_LABELS[key]) {
    return PREF_LABELS[key][I18n.lang] || PREF_LABELS[key].zh || PREF_LABELS[key].en || key;
  }
  return this._humanizeSlug(key) || key;
};

MealEnginePage._nutrientLabel = function(name) {
  const text = String(name || '').trim();
  const zhMap = {
    'Vitamin E': '维生素 E',
    'Vitamin D': '维生素 D',
    Calcium: '钙',
    Iron: '铁',
    Zinc: '锌',
    Iodine: '碘',
  };
  return I18n.lang === 'zh' ? (zhMap[text] || text) : text;
};

MealEnginePage._formatDateShort = function(dateStr) {
  const [year, month, day] = String(dateStr || '').split('-').map(Number);
  if (!year || !month || !day) return dateStr;
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  return date.toLocaleDateString(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'numeric',
    day: 'numeric',
  });
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

MealEnginePage._normalizeClosedLoopIssue = function(value) {
  let detail = value;
  if (typeof detail === 'string') {
    const text = detail.trim();
    if (!text.startsWith('{')) return null;
    try { detail = JSON.parse(text); } catch { return null; }
  }
  if (!detail || typeof detail !== 'object' || detail.error !== 'not_closed_loop') return null;

  const labelMap = {
    staple: { zh: '主食 / 碳水来源', en: 'Staples / carbohydrates' },
    lean_protein: { zh: '低脂蛋白', en: 'Lean protein' },
    red_meat_shellfish: { zh: '红肉 / 贝类', en: 'Red meat / shellfish' },
    calcium: { zh: '钙源', en: 'Calcium source' },
    iodine: { zh: '碘源', en: 'Iodine source' },
    vitamin_d: { zh: '维生素 D 来源', en: 'Vitamin D source' },
    dark_green_cruciferous: { zh: '深绿叶菜 / 十字花科', en: 'Dark-green / cruciferous' },
    vitamin_e_healthy_fat: { zh: '维生素 E / 健康脂肪', en: 'Vitamin E / healthy fat' },
  };

  const rawBuckets = Array.isArray(detail.missing_blocking_buckets)
    ? detail.missing_blocking_buckets
    : Array.isArray(detail.blocking_buckets)
      ? detail.blocking_buckets
      : [];
  const missingBuckets = rawBuckets.map(item => {
    if (typeof item === 'string') {
      const label = labelMap[item] || { zh: item, en: item };
      return {
        bucket: item,
        label_zh: label.zh,
        label_en: label.en,
        recommended_foods: [],
      };
    }
    const bucket = item.bucket || item.ref || '';
    const label = labelMap[bucket] || {};
    return {
      bucket,
      label_zh: item.label_zh || label.zh || bucket,
      label_en: item.label_en || label.en || bucket,
      recommended_foods: Array.isArray(item.recommended_foods) ? item.recommended_foods : [],
    };
  });

  const recommended = new Map();
  (detail.recommended_foods || []).forEach(food => {
    if (food?.slug) recommended.set(food.slug, food);
  });
  missingBuckets.forEach(bucket => {
    (bucket.recommended_foods || []).forEach(food => {
      if (food?.slug && !recommended.has(food.slug)) recommended.set(food.slug, food);
    });
  });

  return {
    error: 'not_closed_loop',
    message_zh: detail.message_zh || '',
    message_en: detail.message_en || '',
    missing_blocking_buckets: missingBuckets,
    recommended_foods: Array.from(recommended.values()),
    added_slugs: [],
    action_message: '',
  };
};

MealEnginePage._renderClosedLoopIssue = function(issue) {
  const t = k => I18n.t(k);
  const lang = I18n.lang;
  const missingRows = (issue.missing_blocking_buckets || []).map(item => `
    <div class="plan-issue-row">
      <div>
        <strong>${this._esc(item[`label_${lang}`] || item.label_en || item.bucket)}</strong>
        <div class="muted">${t('plan.closed_loop_bucket_help')}</div>
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
        <button type="button" class="btn btn-sm" data-closed-loop-add="${this._esc(food.slug)}" ${added ? 'disabled' : ''}>
          ${added ? t('plan.issue_added_notice') : t('plan.issue_add_pref_btn')}
        </button>
      </div>`;
  }).join('');

  return `
    <div class="card plan-issue-card">
      <div class="flex-row">
        <div>
          <h4>${t('plan.closed_loop_title')}</h4>
          <div class="muted">${this._esc(issue[`message_${lang}`] || issue.message_en || '')}</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm" id="mp-closed-loop-add-all-refresh" ${allAdded || !(issue.recommended_foods || []).length ? 'disabled' : ''}>
          ${t('plan.closed_loop_add_all_and_refresh')}
        </button>
      </div>
      ${issue.action_message ? `<div class="plan-issue-feedback">${this._esc(issue.action_message)}</div>` : ''}
      <div class="plan-issue-grid">
        <div>
          <h5>${t('plan.closed_loop_missing_list')}</h5>
          <div class="plan-issue-list">${missingRows || `<div class="muted">${t('plan.closed_loop_unknown_gap')}</div>`}</div>
        </div>
        <div>
          <h5>${t('plan.issue_recommendations_title')}</h5>
          <div class="plan-recommend-grid">${recommendationCards || `<div class="muted">${t('plan.issue_no_supported_foods')}</div>`}</div>
        </div>
      </div>
    </div>`;
};

MealEnginePage._bindClosedLoopIssueActions = function(panel, issue) {
  const t = k => I18n.t(k);
  panel.querySelectorAll('[data-closed-loop-add]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const slug = btn.getAttribute('data-closed-loop-add');
      const food = (issue.recommended_foods || []).find(item => item.slug === slug);
      if (!food) return;
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = t('common.loading');
      try {
        const result = await this._addRecommendedFoodsToPreferences([food], { refreshPool: false, panel });
        if (result.added.length) {
          issue.added_slugs = Array.from(new Set([...(issue.added_slugs || []), ...result.added]));
          btn.textContent = t('plan.issue_added_notice');
        } else {
          btn.disabled = false;
          btn.textContent = originalText;
          issue.action_message = t('plan.issue_no_supported_foods');
        }
      } catch (error) {
        btn.disabled = false;
        btn.textContent = originalText;
        alert(`${t('common.error')}: ${this._userFacingMessage(error.detail || error.message)}`);
      }
    });
  });

  document.getElementById('mp-closed-loop-add-all-refresh')?.addEventListener('click', async () => {
    const foods = issue.recommended_foods || [];
    if (!foods.length) return;
    const btn = document.getElementById('mp-closed-loop-add-all-refresh');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = t('common.loading');
    try {
      const result = await this._addRecommendedFoodsToPreferences(foods, { panel, refreshPool: true });
      if (!result.added.length && result.skipped.length) {
        btn.disabled = false;
        btn.textContent = originalText;
        issue.action_message = t('plan.issue_no_supported_foods');
        panel.innerHTML = this._renderClosedLoopIssue(issue);
        this._bindClosedLoopIssueActions(panel, issue);
      }
    } catch (error) {
      btn.disabled = false;
      btn.textContent = originalText;
      alert(`${t('common.error')}: ${this._userFacingMessage(error.detail || error.message)}`);
    }
  });
};

MealEnginePage._normalizePoolDish = function(dish, fallbackMealType, defaultSource = 'generated') {
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
    recipe_id: dish.recipe_id == null ? null : Number(dish.recipe_id),
    meal_type: mealType,
    name: String(displayName || this._sketchDishName(ingredients, mealType)),
    source: String(dish.source || defaultSource || 'generated'),
    source_label: dish.source_label || null,
    source_label_zh: dish.source_label_zh || '',
    source_label_en: dish.source_label_en || '',
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

MealEnginePage._normalizePoolPayload = function(data, { namedWithLLM = false, source = 'named', defaultDishSource = 'generated' } = {}) {
  const breakfastSource = data.breakfast_dishes || data.breakfast_pool || [];
  const mainSource = data.main_dishes || data.main_pool || [];
  const requiresBreakfastPool = typeof data.requires_breakfast_pool === 'boolean'
    ? data.requires_breakfast_pool
    : Number(data.required_slot_counts?.breakfast ?? 0) > 0;
  const requiresMainPool = typeof data.requires_main_pool === 'boolean'
    ? data.requires_main_pool
    : (Number(data.required_slot_counts?.lunch ?? 0) + Number(data.required_slot_counts?.dinner ?? 0)) > 0;
  const breakfastDishes = requiresBreakfastPool
    ? breakfastSource.map(dish => this._normalizePoolDish(dish, 'breakfast', defaultDishSource))
    : [];
  const mainDishes = requiresMainPool
    ? mainSource.map(dish => this._normalizePoolDish(dish, 'main', defaultDishSource))
    : [];
  const startDate = data.start_date || data.week_skeleton?.[0]?.date || '';
  const poolFingerprint = dishes => dishes.map(dish => [
    dish.dish_id,
    dish.name,
    (dish.ingredient_slugs || []).join(','),
    (dish.ingredients || []).map(item => `${item.slug}:${Number(item.grams || 0)}`).join(','),
    Number(dish.totals?.kcal || 0),
    Number(dish.totals?.protein_g || 0),
    Number(dish.totals?.carbs_g || 0),
    Number(dish.totals?.fat_g || 0),
  ].join('~')).join('|');
  const variant = Number(data.variant ?? 0);
  return {
    pool_tag: `${source}:${startDate}:v${variant}:${poolFingerprint(breakfastDishes)}::${poolFingerprint(mainDishes)}`,
    named_with_llm: namedWithLLM,
    source,
    variant,
    start_date: startDate,
    breakfast_dishes: breakfastDishes,
    main_dishes: mainDishes,
    week_skeleton: Array.isArray(data.week_skeleton) ? data.week_skeleton.slice() : [],
    required_slot_counts: data.required_slot_counts || {},
    requires_breakfast_pool: requiresBreakfastPool,
    requires_main_pool: requiresMainPool,
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

MealEnginePage._hashText = function(text) {
  let hash = 0;
  const value = String(text || '');
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
};

MealEnginePage._clonePoolDish = function(dish) {
  try {
    return JSON.parse(JSON.stringify(dish || {}));
  } catch {
    return { ...(dish || {}) };
  }
};

MealEnginePage._poolDishSignature = function(dish) {
  const number = value => (Number.isFinite(Number(value)) ? Number(value) : 0);
  const ingredients = (Array.isArray(dish?.ingredients) ? dish.ingredients : [])
    .map(item => [
      String(item.slug || item.name || '').trim().toLowerCase(),
      number(item.grams).toFixed(1),
    ].join(':'))
    .filter(item => item !== ':0.0')
    .sort()
    .join('|');
  const fallbackSlugs = (Array.isArray(dish?.ingredient_slugs) ? dish.ingredient_slugs : [])
    .map(slug => String(slug || '').trim().toLowerCase())
    .filter(Boolean)
    .sort()
    .join('|');
  const totals = dish?.totals || {};
  const identity = ingredients || fallbackSlugs || String(dish?.name || '').trim().toLowerCase();
  return [
    identity,
    number(totals.kcal).toFixed(0),
    number(totals.protein_g).toFixed(1),
    number(totals.carbs_g).toFixed(1),
    number(totals.fat_g).toFixed(1),
  ].join('~');
};

MealEnginePage._buildPoolCarryover = function(poolData) {
  if (!poolData) return null;
  const buildGroup = (group, dishes) => this._selectedDishes(group, dishes || [])
    .map((dish, index) => {
      const copy = this._clonePoolDish(dish);
      const signature = this._poolDishSignature(copy) || `${group}:${index}`;
      copy.dish_id = `keep-${group}-${this._hashText(signature)}-${index}`;
      copy.original_dish_id = String(dish.dish_id || '');
      copy.carried_from_previous_pool = true;
      return copy;
    });
  const carryover = {
    breakfast: this._requiresBreakfastPool(poolData) ? buildGroup('breakfast', poolData.breakfast_dishes) : [],
    main: this._requiresMainPool(poolData) ? buildGroup('main', poolData.main_dishes) : [],
  };
  return carryover.breakfast.length || carryover.main.length ? carryover : null;
};

MealEnginePage._mergePoolCarryover = function(poolData) {
  const carryover = this._cache.pool_carryover;
  this._cache.pool_carryover = null;
  if (!carryover) return poolData;

  const mergeGroup = (group, currentDishes) => {
    const current = Array.isArray(currentDishes) ? currentDishes : [];
    const kept = [];
    const keptSignatures = new Set();
    (carryover[group] || []).forEach((dish, index) => {
      const signature = this._poolDishSignature(dish);
      if (!signature || keptSignatures.has(signature)) return;
      const copy = this._clonePoolDish(dish);
      copy.dish_id = `keep-${group}-${this._hashText(signature)}-${index}`;
      copy.carried_from_previous_pool = true;
      kept.push(copy);
      keptSignatures.add(signature);
    });
    const rest = current.filter(dish => !keptSignatures.has(this._poolDishSignature(dish)));
    return { dishes: [...kept, ...rest], count: kept.length, signatures: kept.map(dish => this._poolDishSignature(dish)) };
  };

  const breakfast = this._requiresBreakfastPool(poolData)
    ? mergeGroup('breakfast', poolData.breakfast_dishes)
    : { dishes: [], count: 0, signatures: [] };
  const main = this._requiresMainPool(poolData)
    ? mergeGroup('main', poolData.main_dishes)
    : { dishes: [], count: 0, signatures: [] };
  const total = breakfast.count + main.count;
  if (!total) return poolData;

  return {
    ...poolData,
    pool_tag: `${poolData.pool_tag}:keep:${this._hashText([...breakfast.signatures, ...main.signatures].join('|'))}`,
    breakfast_dishes: breakfast.dishes,
    main_dishes: main.dishes,
    carryover_counts: {
      breakfast: breakfast.count,
      main: main.count,
      total,
    },
  };
};

MealEnginePage._storageUserScope = function() {
  const user = (typeof App !== 'undefined' && App._user) ? App._user : null;
  if (user?.id != null) return `user:${user.id}`;
  const token = localStorage.getItem('ch_access_token') || '';
  let hash = 0;
  for (let i = 0; i < token.length; i += 1) {
    hash = ((hash << 5) - hash + token.charCodeAt(i)) | 0;
  }
  return token ? `token:${Math.abs(hash)}` : 'anonymous';
};

MealEnginePage._poolHistoryStorageKey = function() {
  return `${this._POOL_HISTORY_STORAGE_KEY}:${this._storageUserScope()}`;
};

MealEnginePage._syncPoolHistoryScope = function() {
  const key = this._poolHistoryStorageKey();
  if (this._cache.pool_history_key === key) return;
  this._cache.pool_history_key = key;
  this._cache.pool_history = null;
  this._cache.meal_plan_pool = null;
  this._cache.pool_selection = null;
  this._cache.pool_carryover = null;
  this._cache.arranged_plan = null;
  this._cache.arrange_issue = null;
  this._cache.pool_variant = 0;
  this._cache.pool_source_filter = 'all';
};

MealEnginePage._loadPoolHistory = function() {
  try {
    const raw = localStorage.getItem(this._poolHistoryStorageKey());
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
  localStorage.setItem(this._poolHistoryStorageKey(), JSON.stringify(trimmed));
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

  const history = this._loadPoolHistory();
  history.unshift(snapshot);
  this._savePoolHistory(history);
};

MealEnginePage._restorePoolSnapshot = async function(snapshotId, panel) {
  const snapshot = this._loadPoolHistory().find(item => item.id === snapshotId);
  if (!snapshot?.pool) return;

  this._cache.meal_plan_pool = snapshot.pool;
  this._cache.pool_carryover = null;
  this._cache.pool_selection = {
    pool_tag: snapshot.selection?.pool_tag || snapshot.pool.pool_tag,
    breakfast: snapshot.pool.requires_breakfast_pool === false
      ? new Set()
      : new Set(snapshot.selection?.breakfast || snapshot.pool.breakfast_dishes.map(dish => dish.dish_id)),
    main: snapshot.pool.requires_main_pool === false
      ? new Set()
      : new Set(snapshot.selection?.main || snapshot.pool.main_dishes.map(dish => dish.dish_id)),
  };
  this._cache.arranged_plan = snapshot.arranged_plan || null;
  this._cache.arrange_issue = null;
  this._cache.pool_source_filter = 'all';

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
    const breakfastCount = pool.requires_breakfast_pool === false
      ? 0
      : Array.isArray(item.selection?.breakfast)
      ? item.selection.breakfast.length
      : (pool.breakfast_dishes || []).length;
    const mainCount = pool.requires_main_pool === false
      ? 0
      : Array.isArray(item.selection?.main)
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
  this._syncPoolHistoryScope();
  if (this._cache.meal_plan_pool) return this._cache.meal_plan_pool;
  this._cache.pool_history = this._cache.pool_history || this._loadPoolHistory();
  const variant = Number(this._cache.pool_variant || 0);

  let normalized;
  try {
    const named = await API.nameMealPlanPool(variant);
    normalized = this._normalizePoolPayload(named, { namedWithLLM: true, source: 'named' });
  } catch (err) {
    const raw = await API.getMealPlanPool(variant);
    normalized = this._normalizePoolPayload(raw, { namedWithLLM: false, source: 'sketch' });
    normalized.warnings.unshift(I18n.t('plan.pool_fallback_warning'));
    const warningMessage = this._userFacingMessage(err?.detail || err?.message);
    if (warningMessage) normalized.warnings.push(warningMessage);
  }

  normalized = this._mergePoolCarryover(normalized);
  this._cache.meal_plan_pool = normalized;
  // display-v2 wiring: the weekly menu overview shows the agent's stored
  // week; hydrate it so the arranged section is populated on first render.
  if (!this._cache.arranged_plan && typeof API.getStoredArrangedWeek === 'function') {
    this._cache.arranged_plan = await API.getStoredArrangedWeek().catch(() => null);
  }
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

MealEnginePage._poolSourceFilterOptions = function() {
  return [
    { key: 'all', label: I18n.t('plan.pool_source_all') },
    { key: 'generated', label: I18n.t('plan.pool_source_generated') },
    { key: 'library', label: I18n.t('plan.pool_source_library') },
    { key: 'supplement', label: I18n.t('plan.pool_source_supplement') },
  ];
};

MealEnginePage._poolSourceKey = function(dish) {
  const raw = String(dish?.source || '').trim().toLowerCase();
  if (!raw) return 'generated';
  if (['generated', 'fresh', 'named', 'sketch', 'solver', 'llm', 'llm_generated'].includes(raw)) return 'generated';
  if (['library', 'recipe_library', 'saved_library', 'saved', 'saved_recipe', 'recipe'].includes(raw)) return 'library';
  if (['supplement', 'supplemental', 'supplemented', 'pool_supplement', 'supplemental_pool'].includes(raw)) return 'supplement';
  return raw;
};

MealEnginePage._poolSourceLabel = function(dish) {
  const lang = I18n.lang;
  const label = dish?.source_label;
  if (label && typeof label === 'object') {
    return label[lang] || label[`label_${lang}`] || label.label || label.en || label.zh || '';
  }
  if (label) return String(label);
  const localized = dish?.[`source_label_${lang}`] || dish?.source_label_en || dish?.source_label_zh;
  if (localized) return String(localized);
  const key = this._poolSourceKey(dish);
  return ({
    generated: I18n.t('plan.pool_source_generated'),
    library: I18n.t('plan.pool_source_library'),
    supplement: I18n.t('plan.pool_source_supplement'),
  })[key] || String(dish?.source || key);
};

MealEnginePage._poolSourceCounts = function(poolData) {
  const counts = { all: 0, generated: 0, library: 0, supplement: 0 };
  const breakfast = this._requiresBreakfastPool(poolData) ? (poolData.breakfast_dishes || []) : [];
  const main = this._requiresMainPool(poolData) ? (poolData.main_dishes || []) : [];
  [...breakfast, ...main].forEach(dish => {
    counts.all += 1;
    const key = this._poolSourceKey(dish);
    counts[key] = (counts[key] || 0) + 1;
  });
  return counts;
};

MealEnginePage._visiblePoolDishes = function(dishes) {
  const active = this._cache.pool_source_filter || 'all';
  if (active === 'all') return dishes || [];
  return (dishes || []).filter(dish => this._poolSourceKey(dish) === active);
};

MealEnginePage._renderPoolSourceFilters = function(poolData) {
  const active = this._cache.pool_source_filter || 'all';
  const counts = this._poolSourceCounts(poolData);
  const buttons = this._poolSourceFilterOptions().map(option => {
    const isActive = option.key === active;
    const cls = isActive ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
    const count = counts[option.key] || 0;
    return `
      <button type="button" class="${cls}" data-pool-source-filter="${this._esc(option.key)}" aria-pressed="${isActive ? 'true' : 'false'}">
        ${this._esc(option.label)} ${count}
      </button>`;
  }).join('');
  return `
    <div class="pool-source-filter" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
      ${buttons}
    </div>`;
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
  this._cache.pool_carryover = reason === 'refresh'
    ? this._buildPoolCarryover(this._cache.meal_plan_pool)
    : null;
  this._archiveCurrentPool(reason);
  this._cache.pool_variant = Number(this._cache.pool_variant || 0) + 1;
  this._cache.meal_plan_pool = null;
  this._cache.pool_selection = null;
  this._cache.arranged_plan = null;
  this._cache.arrange_issue = null;
  this._cache.pool_source_filter = 'all';
  await this._renderMealPlan(panel);
  I18n.apply();
};

MealEnginePage._showRefreshPoolConfirm = function(panel) {
  App.openModal(
    I18n.t('plan.pool_refresh_btn'),
    `<p style="margin:0;color:var(--text-2);line-height:1.65">
       ${this._esc(I18n.t('plan.pool_refresh_confirm'))}
     </p>`,
    `<button class="btn btn-ghost" id="pool-refresh-cancel">${I18n.t('common.cancel')}</button>
     <button class="btn btn-primary" id="pool-refresh-confirm">${I18n.t('plan.pool_refresh_btn')}</button>`
  );

  document.getElementById('pool-refresh-cancel')?.addEventListener('click', () => App.closeModal());
  document.getElementById('pool-refresh-confirm')?.addEventListener('click', async e => {
    e.currentTarget.disabled = true;
    App.closeModal();
    await this._refreshMealPlanPool(panel, 'refresh');
  });
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

MealEnginePage._normalizeRecommendedFood = function(food) {
  if (!food) return null;
  const slug = typeof food === 'string' ? food : food.slug;
  if (!slug) return null;
  return {
    ...(typeof food === 'object' ? food : {}),
    slug,
    name_zh: food.name_zh || food.name || slug,
    name_en: food.name_en || food.name || slug,
    roles: Array.isArray(food.roles) ? food.roles.slice() : [],
    role_labels_zh: Array.isArray(food.role_labels_zh) ? food.role_labels_zh.slice() : [],
    role_labels_en: Array.isArray(food.role_labels_en) ? food.role_labels_en.slice() : [],
  };
};

MealEnginePage._isArrangeActionError = function(error) {
  return [
    'weekly_micronutrients_missing',
    'selection_cannot_cover_reinforcement_day',
    'breakfast_pool_empty',
    'main_pool_empty',
    'arrangement_failed',
  ].includes(error);
};

MealEnginePage._normalizeArrangeIssue = function(detail) {
  if (typeof detail === 'string') {
    const text = detail.trim();
    if (text.startsWith('{')) {
      try { detail = JSON.parse(text); } catch { detail = { message_zh: text, message_en: text }; }
    } else {
      detail = { message_zh: text, message_en: text };
    }
  }
  detail = detail && typeof detail === 'object' ? detail : {};
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
    ? detail.recommended_foods
    : this._collectRecommendedFoods(missingMicronutrients);
  const normalizedRecommendedFoods = recommendedFoods
    .map(food => this._normalizeRecommendedFood(food))
    .filter(Boolean);

  const poolGaps = [
    ...(Array.isArray(detail?.missing_buckets) ? detail.missing_buckets : []),
    ...(Array.isArray(detail?.required_buckets) ? detail.required_buckets : []),
    ...(Array.isArray(detail?.blocking_buckets) ? detail.blocking_buckets : []),
  ].map(item => {
    if (typeof item === 'string') {
      return { key: item, label_zh: item, label_en: item };
    }
    return {
      key: item.bucket || item.key || item.day_type || '',
      label_zh: item.label_zh || item.name_zh || item.bucket || item.key || item.day_type || '',
      label_en: item.label_en || item.name_en || item.bucket || item.key || item.day_type || '',
    };
  }).filter(item => item.key || item.label_zh || item.label_en);
  const missingRoles = missingMicronutrients.map(item => item.role).filter(Boolean);
  const requiredBuckets = [
    ...(Array.isArray(detail?.required_buckets) ? detail.required_buckets : []),
    ...poolGaps.map(item => item.key),
  ].map(item => String(item || '').trim()).filter(Boolean);

  return {
    error: detail?.error || 'weekly_micronutrients_missing',
    message_zh: detail?.message_zh || '',
    message_en: detail?.message_en || '',
    warnings: Array.isArray(detail?.warnings) ? detail.warnings.slice() : [],
    micronutrients,
    missing_micronutrients: missingMicronutrients,
    missing_roles: Array.from(new Set(missingRoles)),
    required_buckets: Array.from(new Set(requiredBuckets)),
    pool_gaps: poolGaps,
    recommended_foods: normalizedRecommendedFoods,
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
  this._cache.preference_catalog = null;
  const added = items.map(item => item.item_key);
  if (refreshPool && panel) {
    await this._refreshMealPlanPool(panel, 'preferences_update');
  }
  return { added, skipped };
};

MealEnginePage._extractSupplementPoolPayload = function(data) {
  const root = data?.pool || data?.supplemented_pool || data?.supplement_pool || data || {};
  let breakfast = root.supplemental_breakfast_dishes
    || root.added_breakfast_dishes
    || root.breakfast_dishes
    || root.breakfast_pool
    || [];
  let main = root.supplemental_main_dishes
    || root.added_main_dishes
    || root.main_dishes
    || root.main_pool
    || [];

  const flat = root.dishes || root.candidates || root.items || [];
  if ((!breakfast.length || !main.length) && Array.isArray(flat)) {
    if (!breakfast.length) breakfast = flat.filter(dish => dish?.meal_type === 'breakfast');
    if (!main.length) main = flat.filter(dish => dish?.meal_type === 'main' || dish?.meal_type === 'lunch' || dish?.meal_type === 'dinner');
  }

  return {
    ...root,
    breakfast_dishes: Array.isArray(breakfast) ? breakfast : [],
    main_dishes: Array.isArray(main) ? main : [],
  };
};

MealEnginePage._buildSupplementPoolBody = function(issue, foods, poolData) {
  const selectedBreakfast = this._selectedDishes('breakfast', poolData.breakfast_dishes || []);
  const selectedMain = this._selectedDishes('main', poolData.main_dishes || []);
  const recommendedFoods = (foods || [])
    .map(food => this._normalizeRecommendedFood(food))
    .filter(Boolean);
  const selectedFoodSlugs = recommendedFoods.map(food => food.slug);
  return {
    error: issue?.error || null,
    issue,
    missing_roles: Array.isArray(issue?.missing_roles) ? issue.missing_roles.slice() : [],
    required_buckets: Array.isArray(issue?.required_buckets) ? issue.required_buckets.slice() : [],
    selected_foods: recommendedFoods,
    selected_food_slugs: selectedFoodSlugs,
    recommended_foods: recommendedFoods,
    current_pool: {
      pool_tag: poolData.pool_tag,
      source: poolData.source,
      variant: poolData.variant,
      start_date: poolData.start_date,
      week_skeleton: poolData.week_skeleton || [],
      required_slot_counts: poolData.required_slot_counts || {},
      requires_breakfast_pool: !!poolData.requires_breakfast_pool,
      requires_main_pool: !!poolData.requires_main_pool,
      breakfast_dishes: poolData.breakfast_dishes || [],
      main_dishes: poolData.main_dishes || [],
    },
    selection: this._serializePoolSelection(this._cache.pool_selection, poolData),
    selected_breakfast_dishes: selectedBreakfast,
    selected_main_dishes: selectedMain,
    breakfast_dishes: poolData.breakfast_dishes || [],
    main_dishes: poolData.main_dishes || [],
  };
};

MealEnginePage._mergeSupplementPool = function(response, poolData) {
  const current = poolData || this._cache.meal_plan_pool;
  if (!current) return { breakfast: 0, main: 0, total: 0 };
  const payload = this._extractSupplementPoolPayload(response);
  const supplement = this._normalizePoolPayload({
    ...payload,
    week_skeleton: payload.week_skeleton || current.week_skeleton || [],
    required_slot_counts: payload.required_slot_counts || current.required_slot_counts || {},
    requires_breakfast_pool: typeof payload.requires_breakfast_pool === 'boolean'
      ? payload.requires_breakfast_pool
      : current.requires_breakfast_pool,
    requires_main_pool: typeof payload.requires_main_pool === 'boolean'
      ? payload.requires_main_pool
      : current.requires_main_pool,
    start_date: payload.start_date || current.start_date,
    variant: payload.variant ?? current.variant,
  }, { namedWithLLM: current.named_with_llm, source: 'supplement', defaultDishSource: 'supplement' });

  const selection = this._cache.pool_selection || {
    breakfast: new Set((current.breakfast_dishes || []).map(dish => dish.dish_id)),
    main: new Set((current.main_dishes || []).map(dish => dish.dish_id)),
  };

  const mergeGroup = (group, existingDishes, incomingDishes) => {
    const existing = Array.isArray(existingDishes) ? existingDishes : [];
    const existingIds = new Set(existing.map(dish => String(dish.dish_id || '')));
    const existingSignatures = new Set(existing.map(dish => this._poolDishSignature(dish)).filter(Boolean));
    const added = [];
    (incomingDishes || []).forEach((dish, index) => {
      const copy = this._clonePoolDish(dish);
      copy.source = copy.source || 'supplement';
      const signature = this._poolDishSignature(copy);
      if (signature && existingSignatures.has(signature)) return;
      if (!copy.dish_id || existingIds.has(String(copy.dish_id))) {
        copy.dish_id = `supplement-${group}-${this._hashText(signature || copy.name || index)}-${index}`;
      }
      copy.source = copy.source || 'supplement';
      copy.source_label = copy.source_label || null;
      existingIds.add(String(copy.dish_id));
      if (signature) existingSignatures.add(signature);
      added.push(copy);
    });
    return { dishes: [...added, ...existing], added };
  };

  const breakfast = this._requiresBreakfastPool(current)
    ? mergeGroup('breakfast', current.breakfast_dishes, supplement.breakfast_dishes)
    : { dishes: [], added: [] };
  const main = this._requiresMainPool(current)
    ? mergeGroup('main', current.main_dishes, supplement.main_dishes)
    : { dishes: [], added: [] };
  const supplementSignatures = [...breakfast.added, ...main.added]
    .map(dish => this._poolDishSignature(dish))
    .filter(Boolean)
    .join('|');
  const total = breakfast.added.length + main.added.length;
  const nextPoolTag = `${current.pool_tag}:supplement:${this._hashText(supplementSignatures || Date.now())}`;

  const breakfastSelection = this._requiresBreakfastPool(current) ? new Set(selection.breakfast || []) : new Set();
  const mainSelection = this._requiresMainPool(current) ? new Set(selection.main || []) : new Set();
  breakfast.added.forEach(dish => breakfastSelection.add(dish.dish_id));
  main.added.forEach(dish => mainSelection.add(dish.dish_id));

  this._cache.meal_plan_pool = {
    ...current,
    pool_tag: nextPoolTag,
    breakfast_dishes: breakfast.dishes,
    main_dishes: main.dishes,
    warnings: [
      ...(current.warnings || []),
      ...(supplement.warnings || []),
    ],
    supplement_counts: {
      breakfast: Number(current.supplement_counts?.breakfast || 0) + breakfast.added.length,
      main: Number(current.supplement_counts?.main || 0) + main.added.length,
      total: Number(current.supplement_counts?.total || 0) + total,
    },
  };
  this._cache.pool_selection = {
    pool_tag: nextPoolTag,
    breakfast: breakfastSelection,
    main: mainSelection,
  };
  if (total > 0) {
    this._cache.pool_source_filter = 'supplement';
  }
  return { breakfast: breakfast.added.length, main: main.added.length, total };
};

MealEnginePage._addFoodsAndSupplementPool = async function(panel, poolData, issue, foods) {
  const result = await this._addRecommendedFoodsToPreferences(foods, { panel, refreshPool: false });
  const addedSet = new Set(issue.added_slugs || []);
  result.added.forEach(item => addedSet.add(item));
  issue.added_slugs = Array.from(addedSet);
  if (!result.added.length) {
    issue.action_message = result.skipped.length
      ? I18n.t('plan.issue_no_supported_foods')
      : I18n.t('plan.issue_no_recommendations');
    return { preference: result, supplement: { breakfast: 0, main: 0, total: 0 } };
  }

  const addedFoods = (foods || []).filter(food => result.added.includes((typeof food === 'string' ? food : food?.slug)));
  const activePool = this._cache.meal_plan_pool || poolData;
  const response = await API.supplementMealPlanPool(this._buildSupplementPoolBody(issue, addedFoods, activePool));
  const counts = this._mergeSupplementPool(response, activePool);
  issue.action_message = counts.total
    ? I18n.t('plan.issue_supplement_added')
        .replace('{b}', counts.breakfast)
        .replace('{m}', counts.main)
    : I18n.t('plan.issue_supplement_empty');
  this._cache.arrange_issue = issue;
  return { preference: result, supplement: counts };
};

MealEnginePage._renderArrangeIssue = function(issue) {
  if (!issue) return '';
  const t = k => I18n.t(k);
  const lang = I18n.lang;
  const title = ({
    weekly_micronutrients_missing: t('plan.issue_title'),
    selection_cannot_cover_reinforcement_day: t('plan.issue_reinforcement_title'),
    breakfast_pool_empty: t('plan.issue_breakfast_empty_title'),
    main_pool_empty: t('plan.issue_main_empty_title'),
    arrangement_failed: t('plan.issue_arrangement_failed_title'),
  })[issue.error] || t('plan.issue_arrangement_failed_title');
  const microRows = (issue.missing_micronutrients || []).map(item => `
    <div class="plan-issue-row">
      <div>
        <strong>${this._esc(item[`label_${lang}`] || item.label_en || item.role)}</strong>
        <div class="muted">${t('plan.issue_gap').replace('{a}', item.actual ?? 0).replace('{t}', item.target ?? 0).replace('{u}', item.unit || '')}</div>
      </div>
    </div>`).join('');
  const poolGapRows = (issue.pool_gaps || []).map(item => `
    <div class="plan-issue-row">
      <div>
        <strong>${this._esc(item[`label_${lang}`] || item.label_en || item.key)}</strong>
        <div class="muted">${t('plan.issue_pool_gap_hint')}</div>
      </div>
    </div>`).join('');
  const missingRows = microRows || poolGapRows || `<div class="muted">${t('plan.issue_pool_gap_hint')}</div>`;

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
          ${added ? t('plan.issue_added_notice') : t('plan.issue_add_pref_and_supplement_btn')}
        </button>
      </div>`;
  }).join('');

  return `
    <div class="card plan-issue-card">
      <div class="flex-row">
        <div>
          <h4>${this._esc(title)}</h4>
          <div class="muted">${this._esc(issue[`message_${lang}`] || issue.message_en || '')}</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm" id="mp-add-all-pref-refresh" ${allAdded || !(issue.recommended_foods || []).length ? 'disabled' : ''}>
          ${t('plan.issue_add_all_and_supplement')}
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
  const carryoverBadge = dish.carried_from_previous_pool
    ? `<span class="pill ok">${I18n.t('plan.pool_carryover_badge')}</span>`
    : '';
  const sourceKey = this._poolSourceKey(dish);
  const sourceClass = sourceKey === 'supplement' ? 'warn' : (sourceKey === 'library' ? 'ok' : '');
  const sourceBadge = `<span class="pill ${sourceClass}" title="${this._esc(dish.source || sourceKey)}">${this._esc(this._poolSourceLabel(dish))}</span>`;
  const chips = `${sourceBadge}${carryoverBadge}${this._formatAffinityChips(dish)}`;
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
          <div class="pool-chip-row">${chips}</div>
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
  const warningHtml = this._renderWarningCard(plan.warnings || [], t('plan.warnings'));
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
  const warningsHtml = this._renderWarningCard(poolData.warnings || [], t('plan.warnings'));
  const historyHtml = this._renderPoolHistory();
  const carryoverCount = Number(poolData.carryover_counts?.total || 0);
  const carryoverPill = carryoverCount
    ? `<span class="pill ok">${t('plan.pool_carryover_summary').replace('{n}', carryoverCount)}</span>`
    : '';
  const sourceFiltersHtml = this._renderPoolSourceFilters(poolData);
  const showBreakfastPool = this._requiresBreakfastPool(poolData);
  const showMainPool = this._requiresMainPool(poolData);
  const visibleBreakfastDishes = showBreakfastPool ? this._visiblePoolDishes(poolData.breakfast_dishes) : [];
  const visibleMainDishes = showMainPool ? this._visiblePoolDishes(poolData.main_dishes) : [];
  const breakfastCards = visibleBreakfastDishes.map(dish => this._renderPoolDishCard(dish, 'breakfast')).join('');
  const mainCards = visibleMainDishes.map(dish => this._renderPoolDishCard(dish, 'main')).join('');
  const breakfastSummaryPill = showBreakfastPool ? '<span class="pill ok" data-pool-breakfast-count></span>' : '';
  const mainSummaryPill = showMainPool ? '<span class="pill ok" data-pool-main-count></span>' : '';
  const breakfastSection = showBreakfastPool ? `
    <div class="card">
      <h4>${t('plan.pool_breakfast_section')}</h4>
      <div class="muted">${t('plan.pool_default_selected')}</div>
      <div class="pool-dish-grid">${breakfastCards || `<div class="muted">${t('plan.no_candidates')}</div>`}</div>
    </div>` : '';
  const mainSection = showMainPool ? `
    <div class="card">
      <h4>${t('plan.pool_main_section')}</h4>
      <div class="pool-dish-grid">${mainCards || `<div class="muted">${t('plan.no_candidates')}</div>`}</div>
    </div>` : '';
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
        ${breakfastSummaryPill}
        ${mainSummaryPill}
        ${carryoverPill}
      </div>
      <div class="muted" data-pool-arrange-hint>${t('plan.pool_arrange_hint')}</div>
      ${sourceFiltersHtml}
    </div>
    ${warningsHtml}
    ${historyHtml}
    ${this._renderWeekSkeleton(poolData.week_skeleton)}
    ${breakfastSection}
    ${mainSection}
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
    this._showRefreshPoolConfirm(panel);
  });

  panel.querySelectorAll('[data-pool-source-filter]').forEach(btn => {
    btn.addEventListener('click', async () => {
      this._cache.pool_source_filter = btn.getAttribute('data-pool-source-filter') || 'all';
      await this._renderMealPlanFromCache(panel, poolData);
      I18n.apply();
    });
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
    const breakfast = this._requiresBreakfastPool(poolData)
      ? this._selectedDishes('breakfast', poolData.breakfast_dishes)
      : [];
    const main = this._requiresMainPool(poolData)
      ? this._selectedDishes('main', poolData.main_dishes)
      : [];
    const breakfastMissing = this._requiresBreakfastPool(poolData) && !breakfast.length;
    const mainMissing = this._requiresMainPool(poolData) && !main.length;
    if (breakfastMissing || mainMissing) {
      const error = breakfastMissing && mainMissing
        ? 'arrangement_failed'
        : (breakfastMissing ? 'breakfast_pool_empty' : 'main_pool_empty');
      this._cache.arrange_issue = this._normalizeArrangeIssue({
        error,
        message_zh: this._poolSelectionMessage(poolData),
        message_en: this._poolSelectionMessage(poolData),
      });
      await this._renderMealPlanFromCache(panel, poolData);
      I18n.apply();
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
      if (btn) btn.textContent = t('plan.procurement_generating');
      let procurement = null;
      try {
        procurement = await API.mealEngineProcurement(plan.start_date || null);
      } catch (procErr) {
        await this._renderMealPlanFromCache(panel, poolData);
        I18n.apply();
        alert(`${t('common.error')}: ${procErr.message}`);
        return;
      }
      this._cache.procurement = procurement;
      this._selectTab('procurement');
      panel.innerHTML = `<div class="card"><div class="loading-state"><span class="spinner"></span> ${t('common.loading')}</div></div>`;
      await this._renderProcurement(panel, procurement);
      I18n.apply();
      App.showToast(t('plan.procurement_ready'), 'success');
    } catch (err) {
      const detail = err.detail || {};
      if (this._isArrangeActionError(detail.error)) {
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
        const food = (this._cache.arrange_issue.recommended_foods || []).find(item => item.slug === slug) || { slug };
        await this._addFoodsAndSupplementPool(panel, poolData, this._cache.arrange_issue, [food]);
        await this._renderMealPlanFromCache(panel, this._cache.meal_plan_pool || poolData);
        I18n.apply();
      } catch (error) {
        if (this._cache.arrange_issue) {
          this._cache.arrange_issue.action_message = `${t('common.error')}: ${this._userFacingMessage(error.detail || error.message)}`;
          await this._renderMealPlanFromCache(panel, this._cache.meal_plan_pool || poolData);
          I18n.apply();
        } else {
          btn.disabled = false;
          btn.textContent = originalText;
        }
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
      await this._addFoodsAndSupplementPool(panel, poolData, issue, foods);
      await this._renderMealPlanFromCache(panel, this._cache.meal_plan_pool || poolData);
      I18n.apply();
    } catch (error) {
      if (this._cache.arrange_issue) {
        this._cache.arrange_issue.action_message = `${t('common.error')}: ${this._userFacingMessage(error.detail || error.message)}`;
        await this._renderMealPlanFromCache(panel, this._cache.meal_plan_pool || poolData);
        I18n.apply();
      } else {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    }
  });
};

MealEnginePage._renderMealPlan = async function(panel) {
  const poolData = await this._ensureMealPlanPool();
  await this._renderMealPlanFromCache(panel, poolData);
};
