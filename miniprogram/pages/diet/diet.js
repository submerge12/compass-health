const api = require('../../utils/request');
const fmt = require('../../utils/format');

const mealTypes = [
  { value: 'breakfast', label: '早餐' },
  { value: 'lunch', label: '午餐' },
  { value: 'dinner', label: '晚餐' },
  { value: 'snack', label: '加餐' }
];

function emptyIngredientRow() {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: '',
    grams: ''
  };
}

Page({
  data: {
    mode: 'manual',
    mealTypes,
    mealTypeIndex: 1,
    manual: {
      food_name: '',
      calories: '',
      protein_g: '',
      carbs_g: '',
      fat_g: ''
    },
    ingredientRows: [emptyIngredientRow()],
    today: { logs: [], totals: {} },
    saving: false,
    error: ''
  },

  onShow() {
    if (!api.isLoggedIn()) {
      api.redirectToLogin();
      return;
    }
    this.loadToday();
  },

  switchMode(event) {
    this.setData({ mode: event.currentTarget.dataset.mode, error: '' });
  },

  onMealTypeChange(event) {
    this.setData({ mealTypeIndex: Number(event.detail.value || 0) });
  },

  onManualInput(event) {
    const key = event.currentTarget.dataset.key;
    this.setData({ [`manual.${key}`]: event.detail.value });
  },

  onIngredientRowInput(event) {
    const index = Number(event.currentTarget.dataset.index);
    const key = event.currentTarget.dataset.key;
    this.setData({ [`ingredientRows[${index}].${key}`]: event.detail.value });
  },

  addIngredientRow() {
    this.setData({
      ingredientRows: [...this.data.ingredientRows, emptyIngredientRow()],
      error: ''
    });
  },

  removeIngredientRow(event) {
    const index = Number(event.currentTarget.dataset.index);
    const rows = this.data.ingredientRows.filter((_, rowIndex) => rowIndex !== index);
    this.setData({
      ingredientRows: rows.length ? rows : [emptyIngredientRow()],
      error: ''
    });
  },

  buildIngredientLines() {
    const lines = [];
    for (const row of this.data.ingredientRows) {
      const name = String(row.name || '').trim();
      const grams = Number(row.grams || 0);
      if (!name && !grams) continue;
      if (!name || !grams || grams <= 0) {
        throw new Error('每一行都需要填写食材和有效克数。');
      }
      lines.push(`${name} ${grams}g`);
    }
    if (!lines.length) {
      throw new Error('请至少填写一种食材。');
    }
    return lines.join('\n');
  },

  async loadToday() {
    try {
      const today = await api.get('/api/diet/today');
      const logs = (today.logs || []).map(item => ({
        ...item,
        meal_label: fmt.mealLabel(item.meal_type),
        macro: `${Math.round(item.protein_g || 0)}P/${Math.round(item.carbs_g || 0)}C/${Math.round(item.fat_g || 0)}F`
      }));
      this.setData({ today: { ...today, logs } });
    } catch (err) {
      this.setData({ error: err.message || '加载饮食记录失败' });
    }
  },

  async save() {
    const meal_type = mealTypes[this.data.mealTypeIndex].value;
    this.setData({ saving: true, error: '' });

    try {
      if (this.data.mode === 'manual') {
        const body = {
          meal_type,
          food_name: this.data.manual.food_name.trim(),
          calories: Number(this.data.manual.calories || 0),
          protein_g: Number(this.data.manual.protein_g || 0),
          carbs_g: Number(this.data.manual.carbs_g || 0),
          fat_g: Number(this.data.manual.fat_g || 0)
        };
        if (!body.food_name || !body.calories) {
          throw new Error('请填写食物名称和热量');
        }
        await api.post('/api/diet/log', body);
        this.setData({
          manual: { food_name: '', calories: '', protein_g: '', carbs_g: '', fat_g: '' }
        });
      } else {
        const ingredients = this.buildIngredientLines();
        const result = await api.post('/api/diet/log-ingredients', { meal_type, ingredients });
        if (result.nutrition_status === 'pending') {
          wx.showToast({ title: '已保存待分析', icon: 'none' });
        }
        this.setData({ ingredientRows: [emptyIngredientRow()] });
      }

      wx.showToast({ title: '已保存', icon: 'success' });
      await this.loadToday();
    } catch (err) {
      this.setData({ error: err.message || '保存失败' });
    } finally {
      this.setData({ saving: false });
    }
  }
});
