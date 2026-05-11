/* ============================================================
   Compass Health — pages/diet.js
   Diet page: Record Diet · Recipes · Meal Plan
   ============================================================ */

const DietPage = {

  /** Cached recipe list loaded from the API */
  _recipes: null,
  _activeTab: 'record',
  _pendingTab: null,
  _selectedMeal: null,
  _todayData: null,

  async render() {
    const el = document.getElementById('page-diet');
    if (!el) return;
    const t = k => I18n.t(k);
    const activeTab = this._pendingTab || this._activeTab || 'record';
    this._pendingTab = null;

    el.innerHTML = `
      <div class="diet-page-head">
        <div>
          <div class="diet-kicker">${t('diet.today_label')}</div>
          <h2>${t('diet.title')}</h2>
        </div>
        <button class="btn btn-primary btn-sm" id="diet-focus-record-btn" type="button">${t('diet.quick_record')}</button>
      </div>

      <!-- Tab bar -->
      <div class="page-tab-bar">
        <button class="page-tab-btn ${activeTab === 'record' ? 'active' : ''}" data-tab="record">${t('diet.tab_record')}</button>
        <button class="page-tab-btn ${activeTab === 'recipes' ? 'active' : ''}" data-tab="recipes">${t('diet.tab_recipes')}</button>
        <button class="page-tab-btn ${activeTab === 'plan' ? 'active' : ''}" data-tab="plan">${t('diet.tab_plan')}</button>
      </div>

      <!-- ── Tab: Diet Record ───────────────────────────────── -->
      <div class="page-tab-panel ${activeTab === 'record' ? 'active' : ''}" id="diet-panel-record">
        <div class="diet-today-layout">
          <section class="diet-today-main">
            <div class="diet-overview">
              <div class="diet-overview-primary">
                <span class="diet-overview-label">${t('diet.total_cal')}</span>
                <div class="diet-overview-value">
                  <strong id="diet-total-cal">0</strong>
                  <span>/ <span id="diet-cal-target">--</span> kcal</span>
                </div>
                <div class="diet-overview-rail">
                  <div class="diet-overview-fill" id="diet-cal-progress"></div>
                </div>
              </div>
              <div class="diet-stat-strip">
                <div class="diet-stat">
                  <span>${t('diet.remaining')}</span>
                  <strong><span id="diet-remaining">--</span> kcal</strong>
                </div>
                <div class="diet-stat">
                  <span>${t('diet.protein_status')}</span>
                  <strong id="diet-protein-status">--</strong>
                </div>
                <div class="diet-stat">
                  <span>${t('diet.meal_progress')}</span>
                  <strong id="diet-meal-progress">0/4</strong>
                </div>
              </div>
              <div class="diet-macro-grid">
                ${['protein','carbs','fat'].map(key => `
                  <div class="diet-macro-card ${key}">
                    <div class="diet-macro-head">
                      <span>${t('diet.' + key)}</span>
                      <strong><span id="macro-${key[0]}-val">0</span>g</strong>
                    </div>
                    <div class="diet-macro-rail">
                      <div class="diet-macro-fill ${key}" id="diet-${key}-progress"></div>
                    </div>
                    <div class="diet-macro-target">/ <span id="diet-${key}-target">--</span>g</div>
                  </div>`).join('')}
              </div>
            </div>

            <div class="diet-meal-grid" id="diet-meal-grid">
              <div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${t('common.loading')}</div>
            </div>

            <div class="diet-log-panel">
              <div class="diet-section-head">
                <div>
                  <div class="card-title">${t('diet.recent_logs')}</div>
                </div>
              </div>
              <div id="diet-log-list">
                <div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${t('common.loading')}</div>
              </div>
            </div>
          </section>

          <aside class="diet-entry-panel" id="diet-entry-panel">
            <div class="diet-entry-title">
              <div>
                <div class="card-title">${t('diet.add')}</div>
                <strong id="diet-entry-meal-label">${t('diet.meal_type')}</strong>
              </div>
              <span class="diet-entry-status" id="diet-entry-status">--</span>
            </div>
            <div class="form-group">
              <label>${t('diet.meal_type')}</label>
              <div class="diet-meal-picker" id="diet-meal-picker">
                ${['breakfast','lunch','dinner','snack'].map(meal => `
                  <button type="button" class="diet-meal-chip" data-meal-option="${meal}">${t('diet.' + meal)}</button>
                `).join('')}
              </div>
              <input type="hidden" id="diet-meal" value="">
              <div class="form-error" id="err-diet-meal"></div>
            </div>
            <div class="form-group">
              <label>${t('diet.ingredients')}</label>
              <div class="form-hint">${t('diet.ingredients_hint')}</div>
              <textarea id="diet-ingredients" class="form-textarea diet-ingredient-input" rows="10"
                placeholder="${t('diet.ingredients_placeholder')}"></textarea>
              <div class="form-error" id="err-diet-ingredients"></div>
            </div>
            <button class="btn btn-primary btn-full" id="diet-log-btn" type="button">${t('diet.log_ingredients_btn')}</button>
          </aside>
        </div>
      </div>

      <!-- ── Tab: Recipes ───────────────────────────────────── -->
      <div class="page-tab-panel ${activeTab === 'recipes' ? 'active' : ''}" id="diet-panel-recipes">
        <!-- Find by ingredients -->
        <div class="card" style="margin-bottom:16px">
          <div class="card-title">${t('diet.find_by_ingredients')}</div>
          <textarea id="ingredient-input" class="form-textarea" rows="4"
            placeholder="${t('diet.ingredient_input_placeholder')}"></textarea>
          <button class="btn btn-primary" id="ingredient-search-btn" style="margin-top:10px">
            ${t('diet.search_recipes_btn')}
          </button>
          <div id="ingredient-results" style="margin-top:16px"></div>
        </div>

        <!-- Recipe library -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap">
            <div class="card-title" style="margin:0">${t('diet.recipe_library')}</div>
            <button class="btn btn-sm btn-primary" id="add-recipe-btn">+ ${t('diet.add_recipe')}</button>
          </div>
          <input type="text" id="recipe-search" class="form-control"
            placeholder="${t('diet.recipe_search')}"
            style="margin-bottom:4px"
            oninput="DietPage._filterRecipes(this.value)">
          <div id="recipe-grid-container"></div>
        </div>
      </div>

      <!-- ── Tab: Meal Plan ─────────────────────────────────── -->
      <div class="page-tab-panel ${activeTab === 'plan' ? 'active' : ''}" id="diet-panel-plan">
        <div class="card">
          <div class="card-title" style="margin-bottom:16px">${t('diet.weekly_plan')}</div>
          <div id="week-plan-container">
            <div style="color:var(--text-3);text-align:center;padding:20px">${t('common.loading')}</div>
          </div>
        </div>
      </div>`;

    // Tab switching
    el.querySelectorAll('.page-tab-btn').forEach(btn => {
      btn.onclick = () => this._switchTab(btn.dataset.tab);
    });

    document.getElementById('diet-log-btn').onclick = () => this._submitRecord();
    document.getElementById('diet-focus-record-btn').onclick = () => {
      this._switchTab('record');
      this._focusRecord();
    };
    el.querySelectorAll('[data-meal-option]').forEach(btn => {
      btn.onclick = () => this._selectMeal(btn.dataset.mealOption, { focus: true });
    });
    document.getElementById('ingredient-search-btn').onclick = () => this._searchByIngredients();
    document.getElementById('add-recipe-btn').onclick = () => this._showAddRecipeModal();

    // Invalidate recipe cache on re-render so fresh data is loaded
    this._recipes = null;
    this._selectMeal(this._selectedMeal || this._suggestMeal(), { focus: false });

    await this._loadTodayData();
    if (activeTab === 'recipes') await this._loadRecipeLibrary();
    if (activeTab === 'plan') await this._renderWeekPlan();
  },

  _switchTab(tab) {
    this._activeTab = tab;
    const el = document.getElementById('page-diet');
    el.querySelectorAll('.page-tab-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.tab === tab));
    el.querySelectorAll('.page-tab-panel').forEach(p =>
      p.classList.toggle('active', p.id === `diet-panel-${tab}`));
    if (tab === 'recipes') this._loadRecipeLibrary();
    if (tab === 'plan')    this._renderWeekPlan();
  },

  /* ── Diet Record Tab ────────────────────────────────────────── */

  async _loadTodayData() {
    try {
      const data = await API.getDietToday();
      this._todayData = data;
      this._updateSummary(data);
      this._renderMealCards(data.logs || []);
      this._renderLogs(data.logs);
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _updateSummary(data) {
    const { totals = {}, remaining_calories } = data;
    const target = data.calorie_target || data.tdee || 0;
    const macroTargets = data.macro_targets || {};
    const setEl = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
    const setWidth = (id, val) => { const e = document.getElementById(id); if (e) e.style.width = `${val}%`; };
    setEl('diet-total-cal', totals.calories || 0);
    setEl('diet-cal-target', target || '--');
    setEl('diet-remaining', Number.isFinite(Number(remaining_calories)) ? remaining_calories : '--');
    setEl('macro-p-val', this._formatMacro(totals.protein_g));
    setEl('macro-c-val', this._formatMacro(totals.carbs_g));
    setEl('macro-f-val', this._formatMacro(totals.fat_g));
    setEl('diet-protein-target', macroTargets.protein_g ? this._formatMacro(macroTargets.protein_g) : '--');
    setEl('diet-carbs-target', macroTargets.carbs_g ? this._formatMacro(macroTargets.carbs_g) : '--');
    setEl('diet-fat-target', macroTargets.fat_g ? this._formatMacro(macroTargets.fat_g) : '--');
    setWidth('diet-cal-progress', this._progressPct(totals.calories, target));
    setWidth('diet-protein-progress', this._progressPct(totals.protein_g, macroTargets.protein_g));
    setWidth('diet-carbs-progress', this._progressPct(totals.carbs_g, macroTargets.carbs_g));
    setWidth('diet-fat-progress', this._progressPct(totals.fat_g, macroTargets.fat_g));

    const loggedMeals = new Set((data.logs || []).map(l => l.meal_type));
    setEl('diet-meal-progress', `${loggedMeals.size}/4`);
    const proteinStatus = data.protein_classification
      ? I18n.t(`diet.protein_band_${data.protein_classification}`)
      : '--';
    setEl('diet-protein-status', proteinStatus);
  },

  _renderLogs(logs) {
    const container = document.getElementById('diet-log-list');
    if (!container) return;
    if (!logs || !logs.length) {
      container.innerHTML = `<div class="diet-empty-state">${I18n.t('diet.no_logs_today')}</div>`;
      return;
    }
    const t = k => I18n.t(k);
    const sorted = [...logs].sort((a, b) => new Date(b.logged_at) - new Date(a.logged_at));
    container.innerHTML = `<div class="diet-log-list">
      ${sorted.map(l => this._logRow(l, t)).join('')}
    </div>`;
  },

  _renderMealCards(logs) {
    const container = document.getElementById('diet-meal-grid');
    if (!container) return;
    const t = k => I18n.t(k);
    const mealOrder = ['breakfast','lunch','dinner','snack'];
    container.innerHTML = mealOrder.map(meal => {
      const items = logs.filter(l => l.meal_type === meal);
      const calories = items.reduce((sum, item) => sum + (item.calories || 0), 0);
      const pending = items.some(item => item.ingredients && item.calories === 0);
      return `
        <article class="diet-meal-card ${items.length ? 'has-logs' : 'is-empty'} ${pending ? 'has-pending' : ''}">
          <div class="diet-meal-card-head">
            <div>
              <span>${t('diet.' + meal)}</span>
              <strong>${items.length ? `${calories} kcal` : t('diet.not_recorded')}</strong>
            </div>
            <button class="btn btn-ghost btn-sm" type="button" data-meal-record="${meal}">${t('diet.record_this')}</button>
          </div>
          <div class="diet-meal-card-body">
            ${items.length
              ? items.map(item => this._mealCardItem(item)).join('')
              : `<div class="diet-empty-line">${t('diet.no_meal_logs')}</div>`}
          </div>
        </article>`;
    }).join('');
    container.querySelectorAll('[data-meal-record]').forEach(btn => {
      btn.onclick = () => this._selectMeal(btn.dataset.mealRecord, { focus: true });
    });
    this._selectMeal(this._selectedMeal || this._suggestMeal(), { focus: false });
  },

  _mealCardItem(item) {
    const pending = item.ingredients && item.calories === 0;
    const preview = item.ingredients ? item.ingredients.split('\n').slice(0, 2).join(' · ') : '';
    return `
      <div class="diet-meal-line">
        <span>${this._esc(item.food_name)}</span>
        ${pending
          ? `<em>${I18n.t('diet.pending_analysis')}</em>`
          : `<em>${item.calories} kcal</em>`}
        ${preview ? `<small>${this._esc(preview)}</small>` : ''}
      </div>`;
  },

  _logRow(log, t) {
    const pending = log.ingredients && log.calories === 0;
    const preview = log.ingredients ? log.ingredients.split('\n').slice(0, 2).join(' · ') : '';
    return `
      <div class="log-item diet-log-item">
        <span class="diet-meal-pill">${t('diet.' + log.meal_type)}</span>
        <div class="log-info">
          <div><strong>${this._esc(log.food_name)}</strong></div>
          ${pending
            ? `<span class="pending-badge">${t('diet.pending_analysis')}</span>
               <span class="log-time">${this._esc(preview)}</span>`
            : `<span class="log-value">${log.calories} kcal</span>
               <span class="log-time">${this._formatMacro(log.protein_g)}g P · ${this._formatMacro(log.carbs_g)}g C · ${this._formatMacro(log.fat_g)}g F</span>`}
        </div>
        <div class="diet-log-actions">
          ${pending ? `<button class="btn btn-ghost btn-sm" type="button" onclick="DietPage._reanalyzeLog(${log.id})">${t('diet.reanalyze')}</button>` : ''}
          <button class="log-delete" type="button" onclick="DietPage._deleteLog(${log.id})">✕</button>
        </div>
      </div>`;
  },

  _selectMeal(meal, { focus = false } = {}) {
    if (!meal) return;
    this._selectedMeal = meal;
    const input = document.getElementById('diet-meal');
    if (input) input.value = meal;
    document.querySelectorAll('[data-meal-option]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mealOption === meal);
    });
    document.querySelectorAll('[data-meal-record]').forEach(btn => {
      btn.closest('.diet-meal-card')?.classList.toggle('is-selected', btn.dataset.mealRecord === meal);
    });
    const mealLabel = document.getElementById('diet-entry-meal-label');
    if (mealLabel) mealLabel.textContent = I18n.t('diet.' + meal);
    const status = document.getElementById('diet-entry-status');
    if (status) {
      const count = (this._todayData?.logs || []).filter(log => log.meal_type === meal).length;
      status.textContent = count ? `${count} ${I18n.t('diet.entries_logged')}` : I18n.t('diet.ready_to_record');
    }
    if (focus) this._focusRecord();
  },

  _focusRecord() {
    const panel = document.getElementById('diet-entry-panel');
    panel?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    document.getElementById('diet-ingredients')?.focus();
  },

  _suggestMeal() {
    const hour = new Date().getHours();
    if (hour < 10) return 'breakfast';
    if (hour < 14) return 'lunch';
    if (hour < 20) return 'dinner';
    return 'snack';
  },

  _formatMacro(value) {
    const number = Number(value || 0);
    const rounded = Math.round(number * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  },

  _progressPct(value, target) {
    const current = Number(value || 0);
    const goal = Number(target || 0);
    if (!goal || goal <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((current / goal) * 100)));
  },

  async _submitRecord() {
    const meal = document.getElementById('diet-meal').value;
    const ingredients = document.getElementById('diet-ingredients').value.trim();
    let ok = true;
    ['err-diet-meal','err-diet-ingredients'].forEach(id => {
      const e = document.getElementById(id); if (e) e.textContent = '';
    });
    if (!meal) { document.getElementById('err-diet-meal').textContent = I18n.t('diet.err_select_meal'); ok = false; }
    if (!ingredients) { document.getElementById('err-diet-ingredients').textContent = I18n.t('diet.err_enter_ingredients'); ok = false; }
    if (!ok) return;

    const btn = document.getElementById('diet-log-btn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18n.t('diet.saving');
    try {
      const result = await API.logDietIngredients({ meal_type: meal, ingredients });
      const pending = result.nutrition_status === 'pending';
      App.showToast(pending ? I18n.t('diet.saved_pending') : I18n.t('diet.saved_estimated'), pending ? 'info' : 'success');
      document.getElementById('diet-ingredients').value = '';
      await this._loadTodayData();
    } catch (err) {
      App.showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  },

  async _deleteLog(id) {
    const isZh = I18n.lang === 'zh';
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">${isZh ? '删除该条饮食记录？' : 'Delete this food log entry?'}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="DietPage._confirmDeleteLog(${id})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmDeleteLog(id) {
    App.closeModal();
    try {
      await API.deleteDietLog(id);
      App.showToast(I18n.lang === 'zh' ? '已删除' : 'Deleted', 'success');
      await this._loadTodayData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _reanalyzeLog(id) {
    const isZh = I18n.lang === 'zh';
    App.showToast(I18n.t('diet.reanalyzing'), 'info');
    try {
      const result = await API.reanalyzeDietLog(id);
      if (result.nutrition_status === 'estimated') {
        App.showToast(I18n.t('diet.reanalyze_done'), 'success');
      } else {
        App.showToast(I18n.t('diet.reanalyze_pending'), 'info');
      }
      await this._loadTodayData();
    } catch (err) {
      App.showToast(err.message || (isZh ? '重新分析失败' : 'Reanalysis failed'), 'error');
    }
  },

  /* ── Recipes Tab ────────────────────────────────────────────── */

  async _loadRecipeLibrary() {
    if (this._recipes === null) {
      const container = document.getElementById('recipe-grid-container');
      if (container) container.innerHTML = `<div style="color:var(--text-3);padding:12px">${I18n.t('common.loading')}</div>`;
      try {
        this._recipes = await API.getRecipes();
      } catch (err) {
        this._recipes = [];
        App.showToast(err.message, 'error');
      }
    }
    this._filterRecipes(document.getElementById('recipe-search')?.value || '');
  },

  _filterRecipes(query = '') {
    const container = document.getElementById('recipe-grid-container');
    if (!container) return;
    const recipes = this._recipes || [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? recipes.filter(r => r.name.toLowerCase().includes(q) || (r.ingredients || '').toLowerCase().includes(q))
      : recipes;

    if (!filtered.length) {
      container.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem;padding:12px 0">${I18n.t('common.no_data')}</div>`;
      return;
    }

    const isZh = I18n.lang === 'zh';
    container.innerHTML = `<div class="recipe-grid">${filtered.map(r => {
      const ingPreview = (r.ingredients || '').split('\n').slice(0, 3).join('\n');
      return `
        <div class="recipe-card">
          ${r.is_builtin ? '' : `<span class="recipe-user-badge">${isZh ? '自定义' : 'Custom'}</span>`}
          <div class="recipe-card-title">${this._esc(r.name)}</div>
          <div class="recipe-card-preview">${this._esc(ingPreview)}</div>
          <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
            <button class="btn btn-ghost btn-sm" onclick="DietPage._showRecipeModal(${r.id})">
              ${isZh ? '查看食谱 →' : 'View recipe →'}
            </button>
            <button class="btn btn-sm" style="background:var(--accent);color:#fff"
              onclick="DietPage._addRecipeToLog(${r.id})">
              ${isZh ? '+ 记录' : '+ Log'}
            </button>
            <button class="btn btn-sm btn-ghost" onclick="DietPage._openAddToPlanModal(${r.id})">
              ${isZh ? '📅 计划' : '📅 Plan'}
            </button>
          </div>
        </div>`;
    }).join('')}</div>`;
  },

  async _showRecipeModal(recipeId) {
    let r = (this._recipes || []).find(x => x.id === recipeId);
    if (!r) {
      try { r = await API.getRecipe(recipeId); } catch { return; }
    }
    const isZh = I18n.lang === 'zh';
    const ingHtml = (r.ingredients || '').split('\n').map(l => `<div style="padding:2px 0">${this._esc(l)}</div>`).join('');
    const stepsHtml = (r.steps || '').split('\n').map(l => `<div style="padding:2px 0">${this._esc(l)}</div>`).join('');
    const safeVideoUrl = this._safeUrl(r.video_url);
    const videoHtml = safeVideoUrl
      ? `<div style="margin-top:14px">
           <div style="font-weight:600;margin-bottom:6px">${I18n.t('diet.recipe_video')}</div>
            <a href="${this._esc(safeVideoUrl)}" target="_blank" rel="noopener"
              class="btn btn-ghost btn-sm">▶ ${isZh ? '观看视频' : 'Watch Video'}</a>
         </div>`
      : `<div style="margin-top:10px;font-size:0.78rem;color:var(--text-3)">${I18n.t('diet.no_video')}</div>`;

    App.openModal(
      this._esc(r.name),
      `<div style="font-size:0.85rem;line-height:1.6">
         <div style="font-weight:600;margin-bottom:6px">${isZh ? '食材' : 'Ingredients'}</div>
         <div style="background:var(--surface-2);border-radius:var(--radius);padding:10px 12px;margin-bottom:14px">${ingHtml}</div>
         <div style="font-weight:600;margin-bottom:6px">${isZh ? '做法' : 'Steps'}</div>
         <div style="color:var(--text-2)">${stepsHtml}</div>
         ${videoHtml}
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="DietPage._addRecipeToLog(${r.id});App.closeModal()">
         ${isZh ? '记录饮食' : 'Log Food'}
       </button>`
    );
  },

  _addRecipeToLog(recipeId) {
    const r = (this._recipes || []).find(x => x.id === recipeId);
    const isZh = I18n.lang === 'zh';
    App.openModal(
      isZh ? '添加到饮食记录' : 'Add to Diet Log',
      `<div class="form-group" style="margin-bottom:0">
         <label style="font-size:0.84rem;font-weight:500;margin-bottom:6px;display:block">
           ${isZh ? '选择餐次' : 'Select Meal Type'}
         </label>
         <select id="modal-meal-type" class="form-control">
           <option value="breakfast">${isZh ? '早餐' : 'Breakfast'}</option>
           <option value="lunch" selected>${isZh ? '午餐' : 'Lunch'}</option>
           <option value="dinner">${isZh ? '晚餐' : 'Dinner'}</option>
           <option value="snack">${isZh ? '加餐' : 'Snack'}</option>
         </select>
         <div style="font-size:0.78rem;color:var(--text-3);margin-top:8px">
           ${isZh ? '将通过 AI 自动估算营养数据' : 'Nutrition estimated by AI'}
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${isZh ? '取消' : 'Cancel'}</button>
       <button class="btn btn-primary" onclick="DietPage._confirmLogRecipe(${recipeId})">${isZh ? '确认' : 'Confirm'}</button>`
    );
  },

  async _confirmLogRecipe(recipeId) {
    const r = (this._recipes || []).find(x => x.id === recipeId);
    if (!r) return;
    const mealType = document.getElementById('modal-meal-type')?.value || 'lunch';
    App.closeModal();
    const isZh = I18n.lang === 'zh';
    try {
      await API.logDietIngredients({ meal_type: mealType, ingredients: r.ingredients || r.name });
      App.showToast(isZh ? '已添加到饮食记录' : 'Added to diet log', 'success');
      // Refresh record tab data in background
      this._loadTodayData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  /* ── Add Custom Recipe ──────────────────────────────────────── */

  _showAddRecipeModal() {
    const t = k => I18n.t(k);
    const isZh = I18n.lang === 'zh';
    App.openModal(
      t('diet.add_custom_recipe'),
      `<div style="display:flex;flex-direction:column;gap:10px;font-size:0.85rem">
         <div class="form-group" style="margin:0">
           <label>${t('diet.custom_recipe_name')} *</label>
           <input id="cr-name" class="form-control" placeholder="${isZh ? '例：番茄炒蛋' : 'e.g. Tomato & Egg Stir-fry'}">
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('diet.custom_recipe_ingredients')}</label>
           <textarea id="cr-ingredients" class="form-textarea" rows="4"
             placeholder="${isZh ? '• 番茄：200 克\n• 鸡蛋：2 个' : '• tomato: 200g\n• egg: 2'}"></textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('diet.custom_recipe_steps')}</label>
           <textarea id="cr-steps" class="form-textarea" rows="4"
             placeholder="${isZh ? '1. 番茄切块…' : '1. Cut tomato…'}"></textarea>
         </div>
         <div class="form-group" style="margin:0">
           <label>${t('diet.custom_recipe_video')}</label>
           <input id="cr-video" class="form-control" placeholder="https://...">
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="DietPage._saveCustomRecipe()">${t('diet.recipe_saved')}</button>`
    );
  },

  async _saveCustomRecipe() {
    const name = document.getElementById('cr-name')?.value.trim();
    const isZh = I18n.lang === 'zh';
    if (!name) {
      App.showToast(isZh ? '请输入菜谱名称' : 'Enter a recipe name', 'error');
      return;
    }
    try {
      const recipe = await API.createRecipe({
        name,
        ingredients: document.getElementById('cr-ingredients')?.value.trim() || null,
        steps: document.getElementById('cr-steps')?.value.trim() || null,
        video_url: document.getElementById('cr-video')?.value.trim() || null,
      });
      App.closeModal();
      this._recipes = null; // invalidate cache
      await this._loadRecipeLibrary();
      App.showToast(isZh ? '菜谱已保存' : 'Recipe saved', 'success');
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  /* ── Ingredient Search ──────────────────────────────────────── */

  async _searchByIngredients() {
    const input = document.getElementById('ingredient-input');
    const resultsEl = document.getElementById('ingredient-results');
    if (!input || !resultsEl) return;
    const text = input.value.trim();
    const isZh = I18n.lang === 'zh';
    if (!text) {
      resultsEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">${isZh ? '请输入食材' : 'Enter ingredients'}</div>`;
      return;
    }

    const btn = document.getElementById('ingredient-search-btn');
    btn.disabled = true;
    btn.textContent = I18n.t('diet.searching');
    resultsEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">${I18n.t('common.loading')}</div>`;

    try {
      const result = await API.matchRecipesByIngredients(text);
      if (result.found) {
        // Cache the returned recipes so modals can look them up
        result.recipes.forEach(r => {
          if (this._recipes && !this._recipes.find(x => x.id === r.id)) {
            this._recipes.push(r);
          }
        });
        resultsEl.innerHTML = `
          <div style="font-weight:600;margin-bottom:10px;color:var(--accent)">
            ${I18n.t('diet.recipe_found')} (${result.recipes.length})
          </div>
          <div class="recipe-grid">
            ${result.recipes.map(r => this._recipeMatchCard(r, isZh)).join('')}
          </div>`;
      } else {
        resultsEl.innerHTML = `
          <div class="recipe-not-found-notice">
            <span style="font-size:1.2rem">🔍</span>
            <div>
              <div style="font-weight:600;margin-bottom:4px">${I18n.t('diet.recipe_not_found')}</div>
              <span class="badge-not-in-db">${I18n.t('diet.recipe_not_in_db')}</span>
            </div>
          </div>`;
      }
    } catch (err) {
      resultsEl.innerHTML = `<div style="color:var(--rust);font-size:0.84rem">${this._esc(err.message)}</div>`;
    }

    btn.disabled = false;
    btn.textContent = I18n.t('diet.search_recipes_btn');
  },

  _recipeMatchCard(r, isZh) {
    const ingPreview = (r.ingredients || '').split('\n').slice(0, 3).join('\n');
    return `
      <div class="recipe-card">
        <div class="recipe-card-title">${this._esc(r.name)}</div>
        <div class="recipe-card-preview">${this._esc(ingPreview)}</div>
        <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" onclick="DietPage._showRecipeModal(${r.id})">
            ${isZh ? '查看食谱 →' : 'View recipe →'}
          </button>
          <button class="btn btn-sm" style="background:var(--accent);color:#fff"
            onclick="DietPage._addRecipeToLog(${r.id})">
            ${isZh ? '+ 记录' : '+ Log'}
          </button>
        </div>
      </div>`;
  },

  /* ── Weekly Meal Plan ───────────────────────────────────────── */

  async _renderWeekPlan() {
    const container = document.getElementById('week-plan-container');
    if (!container) return;
    container.innerHTML = `<div style="color:var(--text-3);text-align:center;padding:20px">${I18n.t('common.loading')}</div>`;

    try {
      const data = await API.getMealPlanWeek();
      this._drawWeekPlan(data);
    } catch (err) {
      container.innerHTML = `<div style="color:var(--rust);padding:12px">${this._esc(err.message)}</div>`;
    }
  },

  _drawWeekPlan(data) {
    const container = document.getElementById('week-plan-container');
    if (!container) return;
    const isZh = I18n.lang === 'zh';
    const today = data.today;

    const mealLabel = {
      breakfast: isZh ? '早' : 'B',
      lunch:     isZh ? '午' : 'L',
      dinner:    isZh ? '晚' : 'D',
    };
    const mealName = {
      breakfast: isZh ? '早餐' : 'Breakfast',
      lunch:     isZh ? '午餐' : 'Lunch',
      dinner:    isZh ? '晚餐' : 'Dinner',
    };

    container.innerHTML = `
      <div class="week-calendar">
        ${data.days.map(day => {
          const isToday = day.date === today;
          // Parse date safely (avoid timezone shift by appending noon)
          const d = new Date(day.date + 'T12:00:00');
          const weekday = d.toLocaleDateString(isZh ? 'zh-CN' : 'en-US', { weekday: 'short' });
          const mmdd = `${d.getMonth() + 1}/${d.getDate()}`;

          return `
            <div class="week-day${isToday ? ' week-day-today' : ''}">
              <div class="week-day-header">
                <div class="week-day-weekday">${weekday}</div>
                <div class="week-day-date">${mmdd}</div>
                ${isToday ? `<div class="week-today-badge">${I18n.t('diet.today_label')}</div>` : ''}
              </div>
              ${['breakfast','lunch','dinner'].map(mt => {
                const entry = day.meals[mt];
                if (entry) {
                  const name = entry.recipe ? entry.recipe.name : (entry.custom_name || '');
                  const hasRecipe = !!entry.recipe_id;
                  return `
                    <div class="meal-slot meal-slot-filled">
                      <span class="meal-slot-label">${mealLabel[mt]}</span>
                      <span class="meal-slot-name" title="${this._esc(name)}">${this._esc(name)}</span>
                      <div class="meal-slot-actions">
                        ${hasRecipe
                          ? `<button class="meal-slot-btn" title="${isZh ? '查看' : 'View'}"
                               onclick="DietPage._showRecipeModal(${entry.recipe_id})">👁</button>`
                          : ''}
                        <button class="meal-slot-btn" title="${isZh ? '移除' : 'Remove'}"
                          onclick="DietPage._removeMealEntry(${entry.entry_id})">✕</button>
                      </div>
                    </div>`;
                } else {
                  return `
                    <div class="meal-slot meal-slot-empty"
                      onclick="DietPage._openAddToPlanModal(null, null, '${day.date}', '${mt}')">
                      <span class="meal-slot-label">${mealLabel[mt]}</span>
                      <span class="meal-slot-add" title="${mealName[mt]}">+</span>
                    </div>`;
                }
              }).join('')}
            </div>`;
        }).join('')}
      </div>`;
  },

  _openAddToPlanModal(recipeId, recipeName, presetDate, presetMeal) {
    const isZh = I18n.lang === 'zh';
    const t = k => I18n.t(k);
    if (recipeId && !recipeName) {
      const recipe = (this._recipes || []).find(r => r.id === recipeId);
      recipeName = recipe?.name || '';
    }

    // Build date options: today ±3
    const today = new Date();
    const dateOpts = Array.from({length: 7}, (_, i) => {
      const d = new Date(today);
      d.setDate(today.getDate() - 3 + i);
      const val = d.toISOString().split('T')[0];
      const label = d.toLocaleDateString(isZh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', weekday: 'short' });
      const isTodayOpt = val === today.toISOString().split('T')[0];
      return `<option value="${val}" ${presetDate === val || (!presetDate && isTodayOpt) ? 'selected' : ''}>
        ${label}${isTodayOpt ? (isZh ? ' (今天)' : ' (Today)') : ''}
      </option>`;
    }).join('');

    const mealOpts = ['breakfast','lunch','dinner'].map(m =>
      `<option value="${m}" ${presetMeal === m ? 'selected' : ''}>${mealName(m, isZh)}</option>`
    ).join('');

    function mealName(m, zh) {
      return { breakfast: zh ? '早餐' : 'Breakfast', lunch: zh ? '午餐' : 'Lunch', dinner: zh ? '晚餐' : 'Dinner' }[m];
    }

    const recipePickerHtml = recipeId
      ? `<input type="hidden" id="atp-recipe-id" value="${recipeId}">
         <div style="font-size:0.84rem;color:var(--text-2);margin-bottom:8px">
           ${isZh ? '菜谱：' : 'Recipe: '}<strong>${this._esc(recipeName || '')}</strong>
         </div>`
      : `<div class="form-group" style="margin:0 0 8px">
           <label style="font-size:0.84rem">${isZh ? '选择菜谱' : 'Select recipe'}</label>
           <select id="atp-recipe-id" class="form-control">
             <option value="">-- ${isZh ? '自定义' : 'Custom name'} --</option>
             ${(this._recipes || []).map(r =>
               `<option value="${r.id}">${this._esc(r.name)}</option>`
             ).join('')}
           </select>
         </div>
         <div class="form-group" style="margin:0 0 8px" id="atp-custom-wrap">
           <label style="font-size:0.84rem">${isZh ? '或输入名称' : 'Or enter name'}</label>
           <input id="atp-custom-name" class="form-control" placeholder="${isZh ? '自定义菜名…' : 'Custom dish name…'}">
         </div>`;

    App.openModal(
      t('diet.select_meal_slot'),
      `<div style="display:flex;flex-direction:column;gap:10px;font-size:0.85rem">
         ${recipePickerHtml}
         <div class="form-group" style="margin:0">
           <label>${t('diet.select_date')}</label>
           <select id="atp-date" class="form-control">${dateOpts}</select>
         </div>
         <div class="form-group" style="margin:0">
           <label>${isZh ? '用餐时段' : 'Meal slot'}</label>
           <select id="atp-meal" class="form-control">${mealOpts}</select>
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="DietPage._confirmAddToPlan(${recipeId ? recipeId : 'null'})">
         ${t('diet.add_to_plan')}
       </button>`
    );
  },

  async _confirmAddToPlan(recipeId) {
    const date = document.getElementById('atp-date')?.value;
    const mealType = document.getElementById('atp-meal')?.value;
    const isZh = I18n.lang === 'zh';

    let resolvedRecipeId = recipeId;
    let customName = null;

    if (!recipeId) {
      const sel = document.getElementById('atp-recipe-id');
      if (sel && sel.value) {
        resolvedRecipeId = parseInt(sel.value, 10);
      } else {
        customName = document.getElementById('atp-custom-name')?.value.trim() || null;
        if (!customName) {
          App.showToast(isZh ? '请选择或输入菜谱' : 'Select or enter a recipe', 'error');
          return;
        }
      }
    }

    App.closeModal();
    try {
      await API.addMealPlanEntry({
        date,
        meal_type: mealType,
        recipe_id: resolvedRecipeId || null,
        custom_name: customName,
      });
      App.showToast(I18n.t('diet.plan_added'), 'success');
      // Refresh the week plan if it's currently visible
      if (document.getElementById('diet-panel-plan')?.classList.contains('active')) {
        await this._renderWeekPlan();
      }
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _removeMealEntry(entryId) {
    const isZh = I18n.lang === 'zh';
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">${I18n.t('diet.confirm_remove')}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="DietPage._confirmRemoveMealEntry(${entryId})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmRemoveMealEntry(entryId) {
    App.closeModal();
    try {
      await API.deleteMealPlanEntry(entryId);
      App.showToast(I18n.lang === 'zh' ? '已移除' : 'Removed', 'success');
      await this._renderWeekPlan();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  /* ── Utility ────────────────────────────────────────────────── */

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  },

  _safeUrl(raw) {
    if (!raw) return '';
    try {
      const url = new URL(String(raw), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch {
      return '';
    }
  },
};
