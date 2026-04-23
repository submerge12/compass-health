/* ============================================================
   Reclaim Health - homepage dashboard
   ============================================================ */

const DashboardPage = {
  _recipeCache: {},

  async render() {
    const el = document.getElementById('page-dashboard');
    if (!el) return;

    const t = k => I18n.t(k);
    el.innerHTML = `<div class="card"><div class="empty-state">${t('common.loading')}</div></div>`;

    const [
      userRes,
      waterRes,
      exerciseRes,
      dietRes,
      conditionRes,
      activityRes,
      weekRes,
      procurementRes,
      fixedRes,
      prefsRes,
    ] = await Promise.allSettled([
      API.getMe(),
      API.getWaterToday(),
      API.getExerciseToday(),
      API.getDietToday(),
      API.getConditionToday(),
      API.getDailyActivityToday(),
      API.getMealPlanWeek(),
      API.mealEngineProcurement(null),
      API.listFixedMeals(),
      API.getFoodPreferences(),
    ]);

    const data = {
      user: userRes.status === 'fulfilled' ? userRes.value : null,
      water: waterRes.status === 'fulfilled' ? waterRes.value : null,
      exercise: exerciseRes.status === 'fulfilled' ? exerciseRes.value : null,
      diet: dietRes.status === 'fulfilled' ? dietRes.value : null,
      condition: conditionRes.status === 'fulfilled' ? conditionRes.value : null,
      activity: activityRes.status === 'fulfilled' ? activityRes.value : null,
      week: weekRes.status === 'fulfilled' ? weekRes.value : null,
      procurement: procurementRes.status === 'fulfilled' ? procurementRes.value : null,
      fixedMeals: fixedRes.status === 'fulfilled' ? (fixedRes.value.items || []) : [],
      preferences: prefsRes.status === 'fulfilled' ? prefsRes.value : null,
    };

    const recipeMap = await this._loadRecipeDetails(data.week);
    const todayPlan = this._todayPlan(data.week);

    el.innerHTML = `
      <div class="home-page">
        ${this._renderHero(data, todayPlan, recipeMap)}
        ${this._renderFeatureGrid()}
        <div class="home-main-grid">
          ${this._renderWeekCard(data.week, data.diet, recipeMap)}
          <div class="home-side-stack">
            ${this._renderTodaySummary(data)}
            ${this._renderFixedAndPreferenceCard(data.fixedMeals, data.preferences)}
            ${this._renderProcurementCard(data.procurement)}
          </div>
        </div>
        ${this._renderProgressCard(data.diet)}
        ${this._renderFlowCard()}
      </div>
    `;

    this._bindCheckIn(data.user);
    I18n.apply();
  },

  async _loadRecipeDetails(week) {
    if (!week || !Array.isArray(week.days)) return this._recipeCache;

    const recipeIds = [];
    week.days.forEach(day => {
      Object.values(day.meals || {}).forEach(entry => {
        if (entry && entry.recipe_id && !this._recipeCache[entry.recipe_id]) {
          recipeIds.push(entry.recipe_id);
        }
      });
    });

    const uniqueIds = [...new Set(recipeIds)];
    if (!uniqueIds.length) return this._recipeCache;

    await Promise.all(uniqueIds.map(async recipeId => {
      try {
        this._recipeCache[recipeId] = await API.getRecipe(recipeId);
      } catch (_) {
        this._recipeCache[recipeId] = null;
      }
    }));

    return this._recipeCache;
  },

  _renderHero(data, todayPlan, recipeMap) {
    const t = k => I18n.t(k);
    const user = data.user || {};
    const diet = data.diet || {};
    const condition = data.condition || {};
    const activity = data.activity || {};
    const featureCount = this._countArrangedMeals(data.week);
    const streak = user.checkin_streak || 0;
    const checkedInToday = !!user.checked_in_today;
    const targetKcal = this._formatNumber(diet.calorie_target || diet.tdee || 0);
    const intakeKcal = this._formatNumber((diet.totals || {}).calories || 0);
    const weightText = condition.weight_kg
      ? `${this._formatNumber(condition.weight_kg, 1)} ${t('common.kg')}`
      : '--';
    const activityLabel = this._activityLabel(activity.activity_level);
    const dayMeals = ['breakfast', 'lunch', 'dinner'].map(mealType => {
      const entry = todayPlan && todayPlan.meals ? todayPlan.meals[mealType] : null;
      return this._renderHeroMeal(mealType, entry, recipeMap);
    }).join('');

    return `
      <section class="home-hero">
        <div class="home-hero-copy">
          <div class="home-hero-eyebrow">${this._esc(t('home.hero.eyebrow'))}</div>
          <div class="home-hero-streak">
            <span>${this._esc(this._greeting())}</span>
            <strong>${this._esc(user.username || user.email || t('app.name'))}</strong>
            <span>${t('home.hero.streak').replace('{n}', this._formatNumber(streak))}</span>
          </div>
          <h2 class="home-hero-title">${this._esc(t('app.name'))}</h2>
          <p class="home-hero-subtitle">${this._esc(t('app.tagline'))}</p>
          <p class="home-hero-description">${this._esc(t('home.hero.description'))}</p>

          <div class="home-hero-actions">
            <button type="button"
                    class="btn btn-primary home-hero-btn"
                    data-app-nav
                    data-page="plan"
                    data-plan-tab="meal_plan"
                    data-nav-key="plan-meal">
              ${this._esc(t('home.hero.primary_cta'))}
            </button>
            <button type="button"
                    class="btn btn-ghost home-hero-btn home-hero-btn-secondary"
                    data-app-nav
                    data-page="plan"
                    data-plan-tab="procurement"
                    data-nav-key="plan-procurement">
              ${this._esc(t('home.hero.secondary_cta'))}
            </button>
            <button type="button"
                    class="btn btn-ghost home-checkin-btn"
                    id="home-checkin-btn"
                    ${checkedInToday ? 'disabled' : ''}>
              ${this._esc(checkedInToday ? t('home.hero.checked_in') : t('home.hero.check_in'))}
            </button>
          </div>

          <div class="home-hero-metrics">
            ${this._renderHeroMetric(t('home.hero.metric_target'), `${targetKcal} ${t('common.kcal')}`)}
            ${this._renderHeroMetric(t('home.hero.metric_intake'), `${intakeKcal} ${t('common.kcal')}`)}
            ${this._renderHeroMetric(t('home.hero.metric_weight'), weightText)}
            ${this._renderHeroMetric(t('home.hero.metric_activity'), activityLabel)}
          </div>
        </div>

        <div class="home-hero-visual">
          <div class="home-hero-visual-badge home-hero-visual-badge-top">
            <span>${this._esc(t('home.hero.metric_intake'))}</span>
            <strong>${intakeKcal} ${t('common.kcal')}</strong>
          </div>
          <div class="home-hero-visual-badge home-hero-visual-badge-right">
            <span>${this._esc(t('home.hero.metric_weight'))}</span>
            <strong>${this._esc(weightText)}</strong>
          </div>
          <div class="home-hero-plan-card">
            <div class="home-hero-plan-head">
              <div>
                <span class="home-card-kicker">${this._esc(t('home.hero.today_plan'))}</span>
                <h3>${this._esc(t('home.hero.plan_heading'))}</h3>
              </div>
              <div class="home-plan-count">
                <strong>${this._formatNumber(featureCount)}</strong>
                <span>${this._esc(t('home.hero.metric_planned'))}</span>
              </div>
            </div>
            <div class="home-hero-plan-list">
              ${dayMeals}
            </div>
            <div class="home-hero-plan-footer">
              <span>${this._esc(t('home.hero.plan_hint'))}</span>
              <strong>${targetKcal} ${t('common.kcal')}</strong>
            </div>
          </div>
        </div>
      </section>
    `;
  },

  _renderHeroMetric(label, value) {
    return `
      <div class="home-hero-metric">
        <span>${this._esc(label)}</span>
        <strong>${this._esc(value)}</strong>
      </div>
    `;
  },

  _renderHeroMeal(mealType, entry, recipeMap) {
    const t = k => I18n.t(k);
    const detail = entry && entry.recipe_id ? recipeMap[entry.recipe_id] : null;
    const name = entry
      ? (entry.recipe && entry.recipe.name) || entry.custom_name || t('home.week.empty')
      : t('home.week.empty');
    const kcal = detail && detail.calories ? `${this._formatNumber(detail.calories)} ${t('common.kcal')}` : '--';

    return `
      <div class="home-hero-plan-item ${entry ? 'is-filled' : 'is-empty'}">
        <div>
          <span class="home-card-kicker">${this._esc(this._mealLabel(mealType))}</span>
          <strong>${this._esc(name)}</strong>
        </div>
        <span>${this._esc(kcal)}</span>
      </div>
    `;
  },

  _renderFeatureGrid() {
    const t = k => I18n.t(k);
    const items = [
      {
        key: 'record',
        number: '01',
        page: 'diet',
        navKey: 'diet',
      },
      {
        key: 'fixed',
        number: '02',
        page: 'plan',
        navKey: 'plan-meal',
        planTab: 'fixed_meals',
      },
      {
        key: 'library',
        number: '03',
        page: 'diet',
        navKey: 'diet-recipes',
        dietTab: 'recipes',
      },
      {
        key: 'goal',
        number: '04',
        page: 'settings',
        navKey: 'settings',
      },
    ];

    return `
      <section class="home-feature-grid">
        ${items.map(item => `
          <button type="button"
                  class="home-feature-card"
                  data-app-nav
                  data-page="${item.page}"
                  ${item.navKey ? `data-nav-key="${item.navKey}"` : ''}
                  ${item.planTab ? `data-plan-tab="${item.planTab}"` : ''}
                  ${item.dietTab ? `data-diet-tab="${item.dietTab}"` : ''}>
            <div class="home-feature-icon">${this._esc(item.number)}</div>
            <div class="home-feature-copy">
              <strong>${this._esc(t(`home.feature_${item.key}_title`))}</strong>
              <span>${this._esc(t(`home.feature_${item.key}_desc`))}</span>
            </div>
          </button>
        `).join('')}
      </section>
    `;
  },

  _renderWeekCard(week, diet, recipeMap) {
    const t = k => I18n.t(k);
    const targetLine = diet && (diet.calorie_target || diet.tdee)
      ? t('home.week.target').replace('{n}', this._formatNumber(diet.calorie_target || diet.tdee))
      : t('home.week.target_empty');

    if (!week || !Array.isArray(week.days) || !week.days.length) {
      return `
        <section class="home-card home-week-card">
          <div class="home-card-header">
            <div>
              <span class="home-card-kicker">${this._esc(t('home.section_week'))}</span>
              <h3>${this._esc(t('home.week.heading'))}</h3>
            </div>
            <span class="home-card-target">${this._esc(targetLine)}</span>
          </div>
          <div class="home-empty-state">${this._esc(t('home.week.no_plan'))}</div>
        </section>
      `;
    }

    const rows = week.days.map(day => {
      const date = new Date(`${day.date}T12:00:00`);
      const weekday = date.toLocaleDateString(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', { weekday: 'short' });
      const mmdd = date.toLocaleDateString(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', { month: 'numeric', day: 'numeric' });
      return `
        <tr class="${day.date === week.today ? 'is-today' : ''}">
          <th>
            <div>${this._esc(weekday)}</div>
            <small>${this._esc(mmdd)}</small>
          </th>
          ${['breakfast', 'lunch', 'dinner'].map(mealType => this._renderWeekMealCell(day.meals ? day.meals[mealType] : null, mealType, recipeMap)).join('')}
        </tr>
      `;
    }).join('');

    return `
      <section class="home-card home-week-card">
        <div class="home-card-header">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_week'))}</span>
            <h3>${this._esc(t('home.week.heading'))}</h3>
          </div>
          <span class="home-card-target">${this._esc(targetLine)}</span>
        </div>
        <div class="home-week-table-wrap">
          <table class="home-week-table">
            <thead>
              <tr>
                <th>${this._esc(t('home.week.day_col'))}</th>
                <th>${this._esc(this._mealLabel('breakfast'))}</th>
                <th>${this._esc(this._mealLabel('lunch'))}</th>
                <th>${this._esc(this._mealLabel('dinner'))}</th>
              </tr>
            </thead>
            <tbody>
              ${rows}
            </tbody>
          </table>
        </div>
      </section>
    `;
  },

  _renderWeekMealCell(entry, mealType, recipeMap) {
    const t = k => I18n.t(k);
    if (!entry) {
      return `
        <td>
          <div class="home-week-meal home-week-meal-empty">
            <span>${this._esc(t('home.week.empty'))}</span>
          </div>
        </td>
      `;
    }

    const name = (entry.recipe && entry.recipe.name) || entry.custom_name || this._mealLabel(mealType);
    const detail = entry.recipe_id ? recipeMap[entry.recipe_id] : null;
    const meta = detail && detail.calories ? `${this._formatNumber(detail.calories)} ${t('common.kcal')}` : t('home.week.custom_meal');

    return `
      <td>
        <div class="home-week-meal">
          <strong>${this._esc(name)}</strong>
          <span>${this._esc(meta)}</span>
        </div>
      </td>
    `;
  },

  _renderTodaySummary(data) {
    const t = k => I18n.t(k);
    const diet = data.diet || {};
    const water = data.water || {};
    const exercise = data.exercise || {};
    const condition = data.condition || {};

    const items = [
      {
        label: t('home.summary_calories'),
        value: `${this._formatNumber((diet.totals || {}).calories || 0)} ${t('common.kcal')}`,
        sub: `${this._formatNumber(diet.calorie_target || diet.tdee || 0)} ${t('common.kcal')}`,
      },
      {
        label: t('home.summary_exercise'),
        value: `${this._formatNumber(exercise.total_minutes || 0)} ${t('common.min')}`,
        sub: `${this._formatNumber(exercise.total_calories || 0)} ${t('common.kcal')}`,
      },
      {
        label: t('home.summary_water'),
        value: `${this._formatNumber(water.total_ml || 0)} ${t('common.ml')}`,
        sub: `${this._formatNumber(water.goal_ml || 2000)} ${t('common.ml')}`,
      },
      {
        label: t('home.summary_weight'),
        value: condition.weight_kg ? `${this._formatNumber(condition.weight_kg, 1)} ${t('common.kg')}` : '--',
        sub: this._conditionSubline(condition),
      },
    ];

    return `
      <section class="home-card">
        <div class="home-card-header compact">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_summary'))}</span>
            <h3>${this._esc(t('home.summary_heading'))}</h3>
          </div>
        </div>
        <div class="home-summary-grid">
          ${items.map(item => `
            <div class="home-summary-card">
              <span>${this._esc(item.label)}</span>
              <strong>${this._esc(item.value)}</strong>
              <small>${this._esc(item.sub)}</small>
            </div>
          `).join('')}
        </div>
      </section>
    `;
  },

  _renderFixedAndPreferenceCard(fixedMeals, preferences) {
    const t = k => I18n.t(k);
    const fixedItems = fixedMeals.slice(0, 5).map(item => `
      <span class="home-chip">
        ${this._esc(`${this._weekdayLabel(item.weekday)} ${this._mealLabel(item.meal_type)} · ${(item.recipe_name || item.custom_name || t('home.week.custom_meal'))}`)}
      </span>
    `).join('');

    const prefItems = this._selectedPreferenceLabels(preferences).slice(0, 8).map(label => `
      <span class="home-chip home-chip-soft">${this._esc(label)}</span>
    `).join('');

    return `
      <section class="home-card">
        <div class="home-card-header compact">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_fixed'))}</span>
            <h3>${this._esc(t('home.fixed_heading'))}</h3>
          </div>
          <button type="button"
                  class="btn btn-ghost btn-sm"
                  data-app-nav
                  data-page="plan"
                  data-plan-tab="fixed_meals"
                  data-nav-key="plan-meal">
            ${this._esc(t('home.fixed_manage'))}
          </button>
        </div>
        <div class="home-mini-section">
          <strong>${this._esc(t('home.fixed_saved_title'))}</strong>
          <div class="home-chip-list">
            ${fixedItems || `<span class="home-muted">${this._esc(t('home.fixed_empty'))}</span>`}
          </div>
        </div>
        <div class="home-mini-section">
          <strong>${this._esc(t('home.fixed_pref_title'))}</strong>
          <div class="home-chip-list">
            ${prefItems || `<span class="home-muted">${this._esc(t('home.preferences_empty'))}</span>`}
          </div>
        </div>
      </section>
    `;
  },

  _renderProcurementCard(procurement) {
    const t = k => I18n.t(k);
    if (!procurement) {
      return `
        <section class="home-card">
          <div class="home-card-header compact">
            <div>
              <span class="home-card-kicker">${this._esc(t('home.section_procurement'))}</span>
              <h3>${this._esc(t('home.procurement_heading'))}</h3>
            </div>
          </div>
          <div class="home-empty-state">${this._esc(t('home.procurement_empty'))}</div>
        </section>
      `;
    }

    if (procurement.feasibility === 'not_closed_loop') {
      return `
        <section class="home-card">
          <div class="home-card-header compact">
            <div>
              <span class="home-card-kicker">${this._esc(t('home.section_procurement'))}</span>
              <h3>${this._esc(t('home.procurement_heading'))}</h3>
            </div>
          </div>
          <div class="home-empty-state">${this._esc(procurement[`message_${I18n.lang}`] || t('home.procurement_needs_setup'))}</div>
        </section>
      `;
    }

    const groups = (procurement.groups || []).slice(0, 4).map((group, index) => {
      const rows = (group.rows || []).slice(0, 4).map(row => `
        <li>
          <span class="home-shopping-dot home-shopping-dot-${(index % 4) + 1}"></span>
          <div>
            <strong>${this._esc((I18n.lang === 'zh' ? row.name_zh : row.name_en) || row.slug)}</strong>
            <small>${this._esc(`${this._formatNumber(row.recommended_g || row.planned_g || 0)} g`)}</small>
          </div>
        </li>
      `).join('');

      const label = I18n.lang === 'zh' ? group.label_zh : group.label_en;
      return `
        <div class="home-shopping-group">
          <strong>${this._esc(label || group.bucket || '')}</strong>
          <ul>
            ${rows}
          </ul>
        </div>
      `;
    }).join('');

    return `
      <section class="home-card">
        <div class="home-card-header compact">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_procurement'))}</span>
            <h3>${this._esc(t('home.procurement_heading'))}</h3>
          </div>
          <button type="button"
                  class="btn btn-ghost btn-sm"
                  data-app-nav
                  data-page="plan"
                  data-plan-tab="procurement"
                  data-nav-key="plan-procurement">
            ${this._esc(t('home.procurement_view_all'))}
          </button>
        </div>
        <div class="home-shopping-stack">
          ${groups || `<div class="home-empty-state">${this._esc(t('home.procurement_empty'))}</div>`}
        </div>
      </section>
    `;
  },

  _renderProgressCard(diet) {
    const t = k => I18n.t(k);
    const totals = diet ? (diet.totals || {}) : {};
    const targets = diet ? (diet.macro_targets || {}) : {};
    const calorieTarget = diet ? (diet.calorie_target || diet.tdee || 0) : 0;

    const items = [
      {
        label: t('home.progress_calories'),
        actual: totals.calories || 0,
        target: calorieTarget,
        color: 'var(--accent)',
        unit: t('common.kcal'),
      },
      {
        label: t('home.progress_protein'),
        actual: totals.protein_g || 0,
        target: targets.protein_g || 0,
        color: 'var(--accent-mid)',
        unit: 'g',
      },
      {
        label: t('home.progress_carbs'),
        actual: totals.carbs_g || 0,
        target: targets.carbs_g || 0,
        color: 'var(--amber)',
        unit: 'g',
      },
      {
        label: t('home.progress_fat'),
        actual: totals.fat_g || 0,
        target: targets.fat_g || 0,
        color: 'var(--rust)',
        unit: 'g',
      },
    ];

    return `
      <section class="home-card home-progress-card">
        <div class="home-card-header">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_progress'))}</span>
            <h3>${this._esc(t('home.progress_heading'))}</h3>
          </div>
        </div>
        <div class="home-progress-grid">
          ${items.map(item => {
            const pct = this._progressPercent(item.actual, item.target);
            const actual = this._formatNumber(item.actual, item.unit === 'g' ? 1 : 0);
            const target = this._formatNumber(item.target, item.unit === 'g' ? 1 : 0);
            return `
              <div class="home-progress-item">
                <div class="home-progress-ring" style="--progress:${pct}%;--ring-color:${item.color}">
                  <div>
                    <strong>${this._formatNumber(pct)}</strong>
                    <span>%</span>
                  </div>
                </div>
                <strong>${this._esc(item.label)}</strong>
                <span>${this._esc(`${actual} / ${target} ${item.unit}`)}</span>
              </div>
            `;
          }).join('')}
        </div>
      </section>
    `;
  },

  _renderFlowCard() {
    const t = k => I18n.t(k);
    const steps = ['record', 'prefer', 'generate', 'procure'];
    return `
      <section class="home-card home-flow-card">
        <div class="home-card-header">
          <div>
            <span class="home-card-kicker">${this._esc(t('home.section_flow'))}</span>
            <h3>${this._esc(t('home.flow_heading'))}</h3>
          </div>
        </div>
        <div class="home-flow-grid">
          ${steps.map((step, index) => `
            <div class="home-flow-step">
              <div class="home-flow-index">${this._esc(`0${index + 1}`)}</div>
              <strong>${this._esc(t(`home.flow_${step}_title`))}</strong>
              <span>${this._esc(t(`home.flow_${step}_desc`))}</span>
            </div>
          `).join('')}
        </div>
      </section>
    `;
  },

  _bindCheckIn(user) {
    const button = document.getElementById('home-checkin-btn');
    if (!button || !user || user.checked_in_today) return;

    button.onclick = async () => {
      button.disabled = true;
      try {
        const result = await API.checkIn();
        const nextUser = {
          ...user,
          checked_in_today: true,
          checkin_streak: result.streak,
          membership_level: result.membership_level,
        };
        App.updateUserInfo(nextUser);
        await this.render();
        App.showToast(I18n.lang === 'zh' ? '今日打卡已完成' : 'Checked in for today', 'success');
      } catch (err) {
        button.disabled = false;
        App.showToast(err.message, 'error');
      }
    };
  },

  _todayPlan(week) {
    if (!week || !Array.isArray(week.days)) return null;
    return week.days.find(day => day.date === week.today) || week.days[0] || null;
  },

  _countArrangedMeals(week) {
    if (!week || !Array.isArray(week.days)) return 0;
    return week.days.reduce((sum, day) => {
      return sum + ['breakfast', 'lunch', 'dinner'].filter(mealType => day.meals && day.meals[mealType]).length;
    }, 0);
  },

  _selectedPreferenceLabels(preferences) {
    if (!preferences || !preferences.categories) return [];

    const labels = [];
    Object.entries(preferences.categories).forEach(([category, keys]) => {
      (keys || []).forEach(key => labels.push(this._preferenceLabel(category, key)));
    });
    return labels;
  },

  _preferenceLabel(category, key) {
    if (typeof PREF_LABELS !== 'undefined' && PREF_LABELS[key]) {
      return PREF_LABELS[key][I18n.lang] || key;
    }
    if (typeof PREF_CATEGORY_LABELS !== 'undefined' && PREF_CATEGORY_LABELS[category] && !key) {
      return PREF_CATEGORY_LABELS[category][I18n.lang] || category;
    }
    return String(key || '').replace(/_/g, ' ');
  },

  _mealLabel(mealType) {
    const key = {
      breakfast: 'diet.breakfast',
      lunch: 'diet.lunch',
      dinner: 'diet.dinner',
      snack: 'diet.snack',
    }[mealType] || 'diet.breakfast';
    return I18n.t(key);
  },

  _weekdayLabel(weekday) {
    if (weekday === null || weekday === undefined) return I18n.t('plan.weekday_any');
    const key = ['plan.weekday_mon', 'plan.weekday_tue', 'plan.weekday_wed', 'plan.weekday_thu', 'plan.weekday_fri', 'plan.weekday_sat', 'plan.weekday_sun'][weekday];
    return key ? I18n.t(key) : I18n.t('plan.weekday_any');
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

  _conditionSubline(condition) {
    if (!condition) return I18n.t('home.summary_no_condition');
    if (condition.body_fat_pct) {
      return I18n.lang === 'zh'
        ? `${this._formatNumber(condition.body_fat_pct, 1)}% 体脂`
        : `${this._formatNumber(condition.body_fat_pct, 1)}% body fat`;
    }
    if (condition.mood) return I18n.t('home.summary_condition_logged');
    return I18n.t('home.summary_no_condition');
  },

  _progressPercent(actual, target) {
    if (!target || target <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((actual / target) * 100)));
  },

  _greeting() {
    const hour = new Date().getHours();
    if (hour >= 18) return I18n.t('dash.greeting_evening');
    if (hour >= 12) return I18n.t('dash.greeting_afternoon');
    return I18n.t('dash.greeting_morning');
  },

  _formatNumber(value, fractionDigits = 0) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '--';
    return new Intl.NumberFormat(I18n.lang === 'zh' ? 'zh-CN' : 'en-US', {
      maximumFractionDigits: fractionDigits,
      minimumFractionDigits: fractionDigits,
    }).format(numeric);
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
