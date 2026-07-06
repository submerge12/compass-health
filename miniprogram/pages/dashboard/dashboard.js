const api = require('../../utils/request');
const fmt = require('../../utils/format');

Page({
  data: {
    loading: false,
    checkingIn: false,
    waterSaving: false,
    weightSaving: false,
    error: '',
    user: {},
    diet: { logs: [], totals: {} },
    water: { logs: [] },
    exercise: { logs: [] },
    condition: {},
    customWater: '',
    weightInput: '',
    weightSummary: '用于体重趋势和热量目标',
    dietPct: 0,
    waterPct: 0
  },

  onShow() {
    if (!api.isLoggedIn()) {
      api.redirectToLogin();
      return;
    }
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: '' });
    try {
      const [user, diet, water, exercise, condition] = await Promise.all([
        api.get('/api/users/me'),
        api.get('/api/diet/today'),
        api.get('/api/water/today'),
        api.get('/api/exercise/today'),
        api.get('/api/condition/today').catch(() => null)
      ]);
      const total = diet.totals ? diet.totals.calories : 0;
      const dietPct = fmt.pct(total, diet.calorie_target);
      const waterPct = fmt.pct(water.total_ml, water.goal_ml);
      const weight = condition && (condition.weight_kg || condition.latest_weight_kg);
      this.setData({
        user,
        diet,
        water,
        exercise,
        condition: condition || {},
        weightInput: weight ? String(weight) : this.data.weightInput,
        weightSummary: this.buildWeightSummary(condition),
        dietPct,
        waterPct
      });
    } catch (err) {
      this.setData({ error: err.message || '加载失败' });
    } finally {
      this.setData({ loading: false });
    }
  },

  buildWeightSummary(condition) {
    if (condition && condition.weight_kg) {
      return `今日已记录 ${condition.weight_kg} kg`;
    }
    if (condition && condition.latest_weight_kg) {
      return `最近记录 ${condition.latest_weight_kg} kg`;
    }
    return '用于体重趋势和热量目标';
  },

  async checkIn() {
    this.setData({ checkingIn: true, error: '' });
    try {
      const result = await api.post('/api/users/checkin');
      this.setData({
        user: {
          ...this.data.user,
          checked_in_today: true,
          checkin_streak: result.streak
        }
      });
      wx.showToast({ title: result.already_checked_in ? '已打卡' : '打卡成功', icon: 'success' });
    } catch (err) {
      this.setData({ error: err.message || '打卡失败' });
    } finally {
      this.setData({ checkingIn: false });
    }
  },

  onCustomWaterInput(event) {
    this.setData({ customWater: event.detail.value });
  },

  async logWater(event) {
    const amount = Number(event.currentTarget.dataset.amount || 0);
    await this.saveWaterAmount(amount);
  },

  async logCustomWater() {
    const amount = Number(this.data.customWater || 0);
    await this.saveWaterAmount(amount, true);
  },

  async saveWaterAmount(amount, clearCustom = false) {
    if (!amount || amount <= 0) {
      this.setData({ error: '请输入有效的饮水量。' });
      return;
    }
    this.setData({ waterSaving: true, error: '' });
    try {
      await api.post('/api/water/log', { amount_ml: amount });
      wx.showToast({ title: `+${amount} ml`, icon: 'success' });
      if (clearCustom) this.setData({ customWater: '' });
      await this.load();
    } catch (err) {
      this.setData({ error: err.message || '饮水记录失败' });
    } finally {
      this.setData({ waterSaving: false });
    }
  },

  onWeightInput(event) {
    this.setData({ weightInput: event.detail.value });
  },

  async saveWeight() {
    const weight = Number(this.data.weightInput || 0);
    if (!weight || weight < 20 || weight > 300) {
      this.setData({ error: '请输入 20-300 kg 之间的体重。' });
      return;
    }
    this.setData({ weightSaving: true, error: '' });
    try {
      const condition = await api.post('/api/condition/log', { weight_kg: weight });
      this.setData({ condition, weightSummary: this.buildWeightSummary(condition) });
      wx.showToast({ title: '体重已保存', icon: 'success' });
      await this.load();
    } catch (err) {
      this.setData({ error: err.message || '体重保存失败' });
    } finally {
      this.setData({ weightSaving: false });
    }
  },

  openSettings() {
    wx.switchTab({ url: '/pages/settings/settings' });
  }
});
