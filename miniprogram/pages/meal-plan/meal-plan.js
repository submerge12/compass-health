const api = require('../../utils/request');
const fmt = require('../../utils/format');
const labels = require('../../utils/labels');

const MEALS = [
  { key: 'breakfast', label: '早餐' },
  { key: 'lunch', label: '午餐' },
  { key: 'dinner', label: '晚餐' }
];

Page({
  data: {
    week: { today: '', days: [] },
    pool: { breakfast: [], main: [] },
    hasPool: false,
    poolSummary: '尚未生成',
    generating: false,
    arranging: false,
    confirming: false,
    error: ''
  },

  onShow() {
    if (!api.isLoggedIn()) {
      api.redirectToLogin();
      return;
    }
    this.loadWeek();
  },

  async loadWeek() {
    try {
      const week = await api.get('/api/meal-plan/week');
      const days = (week.days || []).map(day => ({
        ...day,
        mealItems: MEALS.map(meal => {
          const entry = day.meals && day.meals[meal.key];
          const name = entry
            ? (entry.recipe && entry.recipe.name) || entry.custom_name || '已安排'
            : '未安排';
          return { type: meal.key, label: meal.label, name };
        })
      }));
      this.setData({ week: { ...week, days } });
    } catch (err) {
      this.setData({ error: err.message || '加载餐单失败' });
    }
  },

  async generatePool() {
    this.setData({ generating: true, error: '' });
    try {
      let raw;
      try {
        raw = await api.post('/api/meal-plan/pool/name');
      } catch (nameErr) {
        raw = await api.get('/api/meal-plan/pool');
        wx.showToast({ title: '已用基础菜池', icon: 'none' });
      }

      const pool = this.normalizePool(raw);
      const breakfastCount = pool.breakfast.length;
      const mainCount = pool.main.length;
      this.setData({
        pool,
        hasPool: breakfastCount + mainCount > 0,
        poolSummary: `早餐 ${breakfastCount} 个，午晚餐 ${mainCount} 个`
      });
    } catch (err) {
      const detail = err.detail || {};
      const action = detail.error === 'no_bmr'
        ? '请先到设置页保存身体档案。'
        : detail.error === 'not_closed_loop'
          ? '请先到设置页多选一些主食、蛋白、蔬菜和钙源食材。'
          : '';
      this.setData({ error: `${err.message || '生成失败'}${action ? ` ${action}` : ''}` });
    } finally {
      this.setData({ generating: false });
    }
  },

  normalizePool(raw) {
    const breakfastRaw = raw.breakfast_dishes || raw.breakfast_pool || [];
    const mainRaw = raw.main_dishes || raw.main_pool || [];
    return {
      breakfast: breakfastRaw.map((item, index) => this.normalizeDish(item, 'breakfast', index)),
      main: mainRaw.map((item, index) => this.normalizeDish(item, 'main', index))
    };
  },

  normalizeDish(item, group, index) {
    const dish = item || {};
    const ingredients = this.normalizeIngredients(dish.ingredients || dish.parts || []);
    const totals = dish.totals || {};
    const calories = Math.round(Number(totals.kcal || dish.calories || 0));
    const ingredientText = ingredients
      .slice(0, 3)
      .map(row => `${labels.foodLabel(row.slug)} ${Math.round(row.grams)}g`)
      .join(' / ');
    const dish_id = String(dish.dish_id || dish.sketch_id || dish.recipe_id || `${group}-${index}`);

    return {
      ...dish,
      dish_id,
      meal_type: dish.meal_type || group,
      source: dish.source || 'generated',
      source_label: dish.source_label || '',
      name: dish.name || dish.title || `候选菜 ${index + 1}`,
      ingredients,
      totals: {
        kcal: calories,
        protein_g: Number(totals.protein_g || dish.protein_g || 0),
        carbs_g: Number(totals.carbs_g || dish.carbs_g || 0),
        fat_g: Number(totals.fat_g || dish.fat_g || 0)
      },
      ingredient_slugs: dish.ingredient_slugs || ingredients.map(row => row.slug),
      day_type_affinities: dish.day_type_affinities || [],
      method_steps: dish.method_steps || '',
      seasonings: this.normalizeSeasonings(dish.seasonings || []),
      calories,
      ingredientText: ingredientText || '食材待补充',
      selected: true
    };
  },

  normalizeIngredients(items) {
    if (!Array.isArray(items)) return [];
    return items
      .map(item => ({
        slug: String(item.slug || item.item_key || item.name || '').trim(),
        grams: Number(item.grams || item.amount_g || item.weight_g || 0)
      }))
      .filter(item => item.slug && item.grams > 0);
  },

  normalizeSeasonings(items) {
    if (!Array.isArray(items)) return [];
    return items
      .map(item => ({
        name: String(item.name || '').trim(),
        grams: item.grams == null ? null : Number(item.grams)
      }))
      .filter(item => item.name);
  },

  toggleDish(event) {
    const group = event.currentTarget.dataset.group;
    const index = Number(event.currentTarget.dataset.index);
    const key = `pool.${group}[${index}].selected`;
    const current = this.data.pool[group][index].selected;
    this.setData({ [key]: !current });
  },

  toArrangeDish(dish, group) {
    const payload = {
      dish_id: dish.dish_id,
      meal_type: dish.meal_type || group,
      source: dish.source || 'generated',
      source_label: dish.source_label || '',
      name: dish.name,
      ingredients: dish.ingredients,
      totals: dish.totals,
      ingredient_slugs: dish.ingredient_slugs || [],
      day_type_affinities: dish.day_type_affinities || [],
      method_steps: dish.method_steps || '',
      seasonings: dish.seasonings || []
    };
    if (dish.recipe_id) payload.recipe_id = Number(dish.recipe_id);
    return payload;
  },

  async arrangePlan() {
    const breakfast = this.data.pool.breakfast.filter(item => item.selected).map(item => this.toArrangeDish(item, 'breakfast'));
    const main = this.data.pool.main.filter(item => item.selected).map(item => this.toArrangeDish(item, 'main'));

    if (!breakfast.length && !main.length) {
      this.setData({ error: '请至少选择一个候选菜。' });
      return;
    }

    this.setData({ arranging: true, error: '' });
    try {
      await api.post('/api/meal-plan/arrange', {
        breakfast_dishes: breakfast,
        main_dishes: main
      });
      wx.showToast({ title: '已安排', icon: 'success' });
      await this.loadWeek();
    } catch (err) {
      const detail = err.detail || {};
      const message = detail.message_zh || detail.message_en || err.message || '安排失败';
      this.setData({ error: message });
    } finally {
      this.setData({ arranging: false });
    }
  },

  async confirmToday() {
    const date = this.data.week.today || fmt.todayKey();
    this.setData({ confirming: true, error: '' });
    try {
      await api.post(`/api/meal-plan/confirm?date=${encodeURIComponent(date)}`);
      wx.showToast({ title: '已写入饮食', icon: 'success' });
    } catch (err) {
      this.setData({ error: err.message || '确认失败' });
    } finally {
      this.setData({ confirming: false });
    }
  }
});
