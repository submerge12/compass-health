const api = require('../../utils/request');

Page({
  data: {
    mode: 'login',
    apiBase: '',
    username: '',
    password: '',
    loading: false,
    error: ''
  },

  onLoad() {
    this.setData({ apiBase: api.getApiBase() });
    if (api.isLoggedIn()) {
      wx.switchTab({ url: '/pages/dashboard/dashboard' });
    }
  },

  switchMode(event) {
    this.setData({
      mode: event.currentTarget.dataset.mode,
      error: ''
    });
  },

  onApiBaseInput(event) {
    this.setData({ apiBase: event.detail.value });
  },

  onUsernameInput(event) {
    this.setData({ username: event.detail.value });
  },

  onPasswordInput(event) {
    this.setData({ password: event.detail.value });
  },

  async submit() {
    const username = this.data.username.trim();
    const password = this.data.password;
    const apiBase = this.data.apiBase.trim();

    if (!apiBase) {
      this.setData({ error: '请填写 API 地址' });
      return;
    }
    if (!username || !password) {
      this.setData({ error: '请填写用户名和密码' });
      return;
    }

    api.setApiBase(apiBase);
    this.setData({ loading: true, error: '' });

    try {
      const path = this.data.mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const data = await api.post(path, { username, password }, { auth: false });
      api.saveTokens(data);
      wx.showToast({ title: '已登录', icon: 'success' });
      wx.switchTab({ url: '/pages/dashboard/dashboard' });
    } catch (err) {
      this.setData({ error: err.message || '登录失败' });
    } finally {
      this.setData({ loading: false });
    }
  }
});
