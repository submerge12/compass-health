const api = require('../../utils/request');
const labels = require('../../utils/labels');

const genderOptions = [
  { value: 'female', label: '女' },
  { value: 'male', label: '男' }
];

const goalOptions = [
  { value: 'improve_health', label: '改善健康' },
  { value: 'fat_loss_slow', label: '稳妥减脂' },
  { value: 'fat_loss_moderate', label: '中速减脂' },
  { value: 'body_recomp', label: '减脂增肌' },
  { value: 'muscle_gain_slow', label: '稳妥增肌' }
];

const activityOptions = [
  { value: 'sedentary', label: '久坐' },
  { value: 'lightly_active', label: '轻度活动' },
  { value: 'moderately_active', label: '中等活动' },
  { value: 'strength_training', label: '力量训练' }
];

const categoryOrder = ['grains', 'vegetables', 'fruits', 'meat_low_fat', 'meat_mid_fat', 'soy', 'dairy', 'nuts'];

Page({
  data: {
    apiBase: '',
    user: {},
    settings: {
      daily_water_goal_ml: 2000,
      water_reminder_min: 60,
      language: 'zh'
    },
    bmr: {
      age: '',
      gender: 'female',
      height_cm: '',
      weight_kg: '',
      goal: 'improve_health',
      activity_level: 'lightly_active'
    },
    genderOptions,
    genderIndex: 0,
    goalOptions,
    goalIndex: 0,
    activityOptions,
    activityIndex: 1,
    prefCategories: [],
    savingBmr: false,
    savingSettings: false,
    savingPrefs: false,
    error: ''
  },

  onShow() {
    if (!api.isLoggedIn()) {
      api.redirectToLogin();
      return;
    }
    this.setData({ apiBase: api.getApiBase() });
    this.load();
  },

  async load() {
    this.setData({ error: '' });
    try {
      const [user, settings, prefs] = await Promise.all([
        api.get('/api/users/me'),
        api.get('/api/users/settings'),
        api.get('/api/preferences/food')
      ]);
      this.setData({
        user,
        settings: { ...this.data.settings, ...settings },
        prefCategories: this.buildPrefCategories(prefs.known || {}, prefs.categories || {})
      });
      await this.loadBmr();
    } catch (err) {
      this.setData({ error: err.message || '加载设置失败' });
    }
  },

  async loadBmr() {
    try {
      const bmr = await api.get('/api/users/bmr');
      const next = {
        age: bmr.age || '',
        gender: bmr.gender || 'female',
        height_cm: bmr.height_cm || '',
        weight_kg: bmr.weight_kg || '',
        goal: bmr.goal || 'improve_health',
        activity_level: bmr.profile_activity_level || bmr.activity_level || 'lightly_active'
      };
      this.setBmrWithIndexes(next);
    } catch (err) {
      if (err.status !== 404) {
        this.setData({ error: err.message || '身体档案加载失败' });
      }
    }
  },

  setBmrWithIndexes(bmr) {
    const genderIndex = Math.max(0, genderOptions.findIndex(item => item.value === bmr.gender));
    const goalIndex = Math.max(0, goalOptions.findIndex(item => item.value === bmr.goal));
    const activityIndex = Math.max(0, activityOptions.findIndex(item => item.value === bmr.activity_level));
    this.setData({ bmr, genderIndex, goalIndex, activityIndex });
  },

  buildPrefCategories(known, selected) {
    return categoryOrder
      .filter(category => Array.isArray(known[category]))
      .map(category => {
        const selectedSet = new Set(selected[category] || []);
        return {
          key: category,
          label: labels.categoryLabel(category),
          items: known[category].map(key => ({
            key,
            label: labels.foodLabel(key),
            selected: selectedSet.has(key)
          }))
        };
      });
  },

  onApiBaseInput(event) {
    this.setData({ apiBase: event.detail.value });
  },

  saveApiBase() {
    api.setApiBase(this.data.apiBase);
    wx.showToast({ title: '已保存', icon: 'success' });
  },

  onBmrInput(event) {
    const key = event.currentTarget.dataset.key;
    this.setData({ [`bmr.${key}`]: event.detail.value });
  },

  onGenderChange(event) {
    const genderIndex = Number(event.detail.value || 0);
    this.setData({
      genderIndex,
      'bmr.gender': genderOptions[genderIndex].value
    });
  },

  onGoalChange(event) {
    const goalIndex = Number(event.detail.value || 0);
    this.setData({
      goalIndex,
      'bmr.goal': goalOptions[goalIndex].value
    });
  },

  onActivityChange(event) {
    const activityIndex = Number(event.detail.value || 0);
    this.setData({
      activityIndex,
      'bmr.activity_level': activityOptions[activityIndex].value
    });
  },

  async saveBmr() {
    const body = {
      age: Number(this.data.bmr.age),
      gender: this.data.bmr.gender,
      height_cm: Number(this.data.bmr.height_cm),
      weight_kg: Number(this.data.bmr.weight_kg),
      goal: this.data.bmr.goal
    };
    if (!body.age || !body.height_cm || !body.weight_kg) {
      this.setData({ error: '请填写年龄、身高和体重。' });
      return;
    }

    this.setData({ savingBmr: true, error: '' });
    try {
      await api.post('/api/users/bmr', body);
      await api.patch('/api/users/me/activity-level', { activity_level: this.data.bmr.activity_level });
      wx.showToast({ title: '已保存', icon: 'success' });
      this.loadBmr();
    } catch (err) {
      this.setData({ error: err.message || '保存身体档案失败' });
    } finally {
      this.setData({ savingBmr: false });
    }
  },

  onSettingsInput(event) {
    const key = event.currentTarget.dataset.key;
    this.setData({ [`settings.${key}`]: event.detail.value });
  },

  async saveSettings() {
    this.setData({ savingSettings: true, error: '' });
    try {
      await api.put('/api/users/settings', {
        daily_water_goal_ml: Number(this.data.settings.daily_water_goal_ml || 2000),
        water_reminder_min: Number(this.data.settings.water_reminder_min || 60),
        language: this.data.settings.language || 'zh'
      });
      wx.showToast({ title: '已保存', icon: 'success' });
    } catch (err) {
      this.setData({ error: err.message || '保存设置失败' });
    } finally {
      this.setData({ savingSettings: false });
    }
  },

  togglePreference(event) {
    const catIndex = Number(event.currentTarget.dataset.catIndex);
    const foodIndex = Number(event.currentTarget.dataset.foodIndex);
    const current = this.data.prefCategories[catIndex].items[foodIndex].selected;
    this.setData({
      [`prefCategories[${catIndex}].items[${foodIndex}].selected`]: !current
    });
  },

  async savePreferences() {
    const items = [];
    this.data.prefCategories.forEach(category => {
      category.items.forEach(food => {
        if (food.selected) {
          items.push({ category: category.key, item_key: food.key });
        }
      });
    });

    this.setData({ savingPrefs: true, error: '' });
    try {
      await api.post('/api/preferences/food', { items, replace: true });
      wx.showToast({ title: '已保存', icon: 'success' });
    } catch (err) {
      this.setData({ error: err.message || '保存食材偏好失败' });
    } finally {
      this.setData({ savingPrefs: false });
    }
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '确认退出当前账号？',
      success: async res => {
        if (!res.confirm) return;
        const refreshToken = wx.getStorageSync('ch_refresh_token') || null;
        try {
          await api.post('/api/auth/logout', { refresh_token: refreshToken });
        } catch (err) {
          // Logout should complete locally even when the server is unreachable.
        }
        api.clearTokens();
        wx.reLaunch({ url: '/pages/login/login' });
      }
    });
  }
});
