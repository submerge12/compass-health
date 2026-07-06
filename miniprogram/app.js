App({
  globalData: {
    appName: 'Compass Health'
  },

  onLaunch() {
    const apiBase = wx.getStorageSync('ch_api_base');
    if (!apiBase) {
      wx.setStorageSync('ch_api_base', 'http://127.0.0.1:8000');
    }
  }
});
