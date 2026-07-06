const ACCESS_TOKEN_KEY = 'ch_access_token';
const REFRESH_TOKEN_KEY = 'ch_refresh_token';
const API_BASE_KEY = 'ch_api_base';

function getApiBase() {
  return wx.getStorageSync(API_BASE_KEY) || 'http://127.0.0.1:8000';
}

function setApiBase(value) {
  const clean = String(value || '').trim().replace(/\/+$/, '');
  wx.setStorageSync(API_BASE_KEY, clean || 'http://127.0.0.1:8000');
}

function saveTokens(data) {
  if (!data) return;
  if (data.access_token) wx.setStorageSync(ACCESS_TOKEN_KEY, data.access_token);
  if (data.refresh_token) wx.setStorageSync(REFRESH_TOKEN_KEY, data.refresh_token);
  if (typeof data.has_bmr_profile !== 'undefined') {
    wx.setStorageSync('ch_has_bmr', !!data.has_bmr_profile);
  }
  if (typeof data.is_admin !== 'undefined') {
    wx.setStorageSync('ch_is_admin', !!data.is_admin);
  }
}

function clearTokens() {
  wx.removeStorageSync(ACCESS_TOKEN_KEY);
  wx.removeStorageSync(REFRESH_TOKEN_KEY);
  wx.removeStorageSync('ch_has_bmr');
  wx.removeStorageSync('ch_is_admin');
}

function isLoggedIn() {
  return !!wx.getStorageSync(ACCESS_TOKEN_KEY);
}

function messageFromResponse(data, fallback) {
  if (!data) return fallback || '请求失败';
  const detail = data.detail || data.message || data.error;
  if (!detail) return fallback || '请求失败';
  if (typeof detail === 'string') return detail;
  if (detail.message_zh) return detail.message_zh;
  if (detail.message_en) return detail.message_en;
  if (detail.error) return detail.error;
  try {
    return JSON.stringify(detail);
  } catch (err) {
    return fallback || '请求失败';
  }
}

function redirectToLogin() {
  clearTokens();
  wx.reLaunch({ url: '/pages/login/login' });
}

function request(method, path, data, options = {}) {
  return doRequest(method, path, data, {
    auth: options.auth !== false,
    retryOnUnauthorized: options.retryOnUnauthorized !== false
  });
}

function doRequest(method, path, data, options) {
  const header = {
    'Content-Type': 'application/json',
    'X-Client': 'wechat-miniprogram'
  };

  if (options.auth) {
    const token = wx.getStorageSync(ACCESS_TOKEN_KEY);
    if (token) header.Authorization = `Bearer ${token}`;
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}${path}`,
      method,
      data,
      header,
      timeout: 30000,
      success(res) {
        const status = res.statusCode || 0;
        if (status === 401 && options.auth && options.retryOnUnauthorized) {
          refreshToken()
            .then(() => doRequest(method, path, data, { ...options, retryOnUnauthorized: false }))
            .then(resolve)
            .catch(err => {
              redirectToLogin();
              reject(err);
            });
          return;
        }

        if (status >= 200 && status < 300) {
          resolve(res.data || {});
          return;
        }

        const err = new Error(messageFromResponse(res.data, `HTTP ${status}`));
        err.status = status;
        err.detail = res.data && res.data.detail;
        reject(err);
      },
      fail(err) {
        reject(new Error(`网络连接失败：${err.errMsg || '请检查 API 地址'}`));
      }
    });
  });
}

function refreshToken() {
  const refresh = wx.getStorageSync(REFRESH_TOKEN_KEY);
  if (!refresh) {
    return Promise.reject(new Error('登录已过期，请重新登录'));
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}/api/auth/refresh`,
      method: 'POST',
      data: { refresh_token: refresh },
      header: { 'Content-Type': 'application/json' },
      timeout: 30000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300 && res.data && res.data.access_token) {
          saveTokens(res.data);
          resolve(res.data);
          return;
        }
        reject(new Error(messageFromResponse(res.data, '登录已过期，请重新登录')));
      },
      fail(err) {
        reject(new Error(`刷新登录失败：${err.errMsg || '网络错误'}`));
      }
    });
  });
}

function get(path, options) {
  return request('GET', path, null, options);
}

function post(path, data, options) {
  return request('POST', path, data || {}, options);
}

function put(path, data, options) {
  return request('PUT', path, data || {}, options);
}

function patch(path, data, options) {
  return request('PATCH', path, data || {}, options);
}

function del(path, options) {
  return request('DELETE', path, null, options);
}

module.exports = {
  get,
  post,
  put,
  patch,
  del,
  getApiBase,
  setApiBase,
  saveTokens,
  clearTokens,
  isLoggedIn,
  redirectToLogin,
  messageFromResponse
};
