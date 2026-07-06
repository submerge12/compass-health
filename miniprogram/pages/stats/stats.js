const api = require('../../utils/request');
const fmt = require('../../utils/format');

Page({
  data: {
    summary: { weight_trend: [] },
    weekly: [],
    error: ''
  },

  onShow() {
    if (!api.isLoggedIn()) {
      api.redirectToLogin();
      return;
    }
    this.load();
  },

  async load() {
    this.setData({ error: '' });
    try {
      const [summary, weeklyRaw] = await Promise.all([
        api.get('/api/stats/summary'),
        api.get('/api/stats/weekly')
      ]);
      const maxDiet = Math.max(1, ...weeklyRaw.map(item => Number(item.diet_calories || 0)));
      const maxWater = Math.max(1, ...weeklyRaw.map(item => Number(item.water_ml || 0)));
      const weekly = weeklyRaw.map(item => ({
        ...item,
        label: fmt.compactDate(item.date),
        dietPct: fmt.pct(item.diet_calories, maxDiet),
        waterPct: fmt.pct(item.water_ml, maxWater)
      }));
      this.setData({
        summary: { weight_trend: [], ...summary },
        weekly
      });
    } catch (err) {
      this.setData({ error: err.message || '加载统计失败' });
    }
  }
});
