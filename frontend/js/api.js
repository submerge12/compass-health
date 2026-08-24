/* ============================================================
   Compass Health - api.js
   SECURITY: This is the ONLY file that knows the API base URL.
   All other JS files import from here and never call fetch() directly.
   ============================================================ */

const API_BASE = 'http://localhost:8000';

function _makeOpaqueId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '');
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

function _normalizeActionPath(path) {
  const clean = (path || '/')
    .split('?')[0]
    .replace(/^\/api\//, '')
    .replace(/\/\d+(?=\/|$)/g, '/id');
  return clean
    .split('/')
    .filter(Boolean)
    .map(part => part.replace(/[^a-zA-Z0-9_-]/g, '').replace(/-/g, '_'))
    .join('.') || 'root';
}

function _buildRequestContext(method, path, overrides = {}) {
  return {
    requestId: _makeOpaqueId(),
    journeyId: overrides.journeyId || _makeOpaqueId(),
    uiAction: overrides.uiAction || `${String(method || 'GET').toLowerCase()}.${_normalizeActionPath(path)}`,
  };
}

function _withTracingHeaders(headers, context) {
  return {
    ...headers,
    'X-Request-ID': context.requestId,
    'X-Journey-ID': context.journeyId,
    'X-UI-Action': context.uiAction,
  };
}

const API = {

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Internal: make authenticated request with auto-refresh
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async _request(method, path, body = null, requiresAuth = true) {
    const headers = { 'Content-Type': 'application/json' };

    if (requiresAuth) {
      const token = localStorage.getItem('ch_access_token');
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    const opts = { method, headers };
    if (body !== null) opts.body = JSON.stringify(body);

    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, opts);
    } catch (err) {
      throw new Error('网络错误，请检查连接 / Network error: ' + err.message);
    }

    // 401 鈫?try token refresh, then retry once
    if (res.status === 401 && requiresAuth) {
      const refreshed = await this._tryRefresh();
      if (refreshed) {
        const newToken = localStorage.getItem('ch_access_token');
        headers['Authorization'] = `Bearer ${newToken}`;
        try {
          res = await fetch(`${API_BASE}${path}`, { method, headers, body: body !== null ? JSON.stringify(body) : undefined });
        } catch (err) {
          throw new Error('网络错误，请检查连接 / Network error: ' + err.message);
        }
      } else {
        // Refresh failed - clear tokens and redirect to login
        localStorage.removeItem('ch_access_token');
        localStorage.removeItem('ch_refresh_token');
        localStorage.removeItem('ch_has_bmr');
        localStorage.removeItem('ch_is_admin');
        const wrapped = new Error('Session expired. Please log in again.');
        wrapped.status = 401;
        wrapped.error = 'session_expired';
        throw wrapped;
      }
    }

    // Parse JSON for all responses
    let data;
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try { data = await res.json(); } catch { data = {}; }
    } else {
      try { data = await res.text(); } catch { data = null; }
    }

    if (!res.ok) {
      const msg = (data && (data.detail || data.message || data.error)) || `HTTP ${res.status}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }

    return data;
  },

  /** Attempt a silent token refresh. Returns true on success. */
  async _tryRefresh() {
    const refreshToken = localStorage.getItem('ch_refresh_token');
    if (!refreshToken) return false;
    try {
      const res = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken })
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (data.access_token) {
        localStorage.setItem('ch_access_token', data.access_token);
        if (data.refresh_token) localStorage.setItem('ch_refresh_token', data.refresh_token);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Auth endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async register(username, password) {
    return this._request('POST', '/api/auth/register', { username, password }, false);
  },

  async login(username, password) {
    return this._request('POST', '/api/auth/login', { username, password }, false);
  },

  async logout() {
    const refresh_token = localStorage.getItem('ch_refresh_token') || null;
    try {
      await this._request('POST', '/api/auth/logout', { refresh_token }, true);
    } catch { /* ignore errors on logout */ }
    localStorage.removeItem('ch_access_token');
    localStorage.removeItem('ch_refresh_token');
    localStorage.removeItem('ch_has_bmr');
    localStorage.removeItem('ch_is_admin');
  },

  async refreshToken() {
    return this._tryRefresh();
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     User / Profile endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async getMe() {
    return this._request('GET', '/api/users/me');
  },

  async getBMR() {
    return this._request('GET', '/api/users/bmr');
  },

  async saveBMR(data) {
    return this._request('POST', '/api/users/bmr', data);
  },

  async checkIn() {
    return this._request('POST', '/api/users/checkin');
  },

  async getCheckinStreak() {
    return this._request('GET', '/api/users/checkin/streak');
  },

  async getSettings() {
    return this._request('GET', '/api/users/settings');
  },

  async saveSettings(data) {
    return this._request('PUT', '/api/users/settings', data);
  },

  async updateTargetWeight(target_weight_kg) {
    return this._request('PATCH', '/api/users/me/target-weight', { target_weight_kg });
  },

  async updateWeight(weight_kg) {
    return this._request('PATCH', '/api/users/me/weight', { weight_kg });
  },

  async updateActivityLevel(activity_level) {
    return this._request('PATCH', '/api/users/me/activity-level', { activity_level });
  },

  async getFoodPreferences() {
    return this._request('GET', '/api/preferences/food');
  },

  async saveFoodPreferences(items, { custom = [], replace = true } = {}) {
    return this._request('POST', '/api/preferences/food', { items, custom, replace });
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Daily-activity endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async getDailyActivityToday() {
    return this._request('GET', '/api/daily-activity/today');
  },

  async getDailyActivityDefault() {
    return this._request('GET', '/api/daily-activity/default');
  },

  async saveDailyActivity(activity_level, date = null) {
    const body = { activity_level };
    if (date) body.date = date;
    return this._request('POST', '/api/daily-activity/today', body);
  },

  async getDailyActivityHistory(days = 7) {
    return this._request('GET', `/api/daily-activity/history?days=${days}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Water endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async logWater(amount_ml) {
    return this._request('POST', '/api/water/log', { amount_ml });
  },

  async deleteWaterLog(id) {
    return this._request('DELETE', `/api/water/log/${id}`);
  },

  async getWaterToday() {
    return this._request('GET', '/api/water/today');
  },

  async getWaterHistory(days = 7) {
    return this._request('GET', `/api/water/history?days=${days}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Exercise endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async logExercise(data) {
    return this._request('POST', '/api/exercise/log', data);
  },

  async deleteExerciseLog(id) {
    return this._request('DELETE', `/api/exercise/log/${id}`);
  },

  async getExerciseToday() {
    return this._request('GET', '/api/exercise/today');
  },

  async getExerciseHistory(days = 7) {
    return this._request('GET', `/api/exercise/history?days=${days}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Diet endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async logDiet(data) {
    return this._request('POST', '/api/diet/log', data);
  },

  async logDietIngredients(data) {
    return this._request('POST', '/api/diet/log-ingredients', data);
  },

  async deleteDietLog(id) {
    return this._request('DELETE', `/api/diet/log/${id}`);
  },

  async reanalyzeDietLog(id) {
    return this._request('POST', `/api/diet/log/${id}/reanalyze`, {});
  },

  async getDietToday() {
    return this._request('GET', '/api/diet/today');
  },

  async getDietHistory(days = 7) {
    return this._request('GET', `/api/diet/history?days=${days}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Condition endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async logCondition(data) {
    return this._request('POST', '/api/condition/log', data);
  },

  async getConditionToday() {
    return this._request('GET', '/api/condition/today');
  },

  async getConditionHistory(days = 30) {
    return this._request('GET', `/api/condition/history?days=${days}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Stats endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async getStatsSummary() {
    return this._request('GET', '/api/stats/summary');
  },

  async getStatsWeekly() {
    return this._request('GET', '/api/stats/weekly');
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Recipe endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async getRecipes(q = '') {
    const qs = q ? `?q=${encodeURIComponent(q)}` : '';
    return this._request('GET', `/api/recipes${qs}`);
  },

  async getRecipe(id) {
    return this._request('GET', `/api/recipes/${id}`);
  },

  async createRecipe(data) {
    return this._request('POST', '/api/recipes', data);
  },

  async matchRecipesByIngredients(ingredients) {
    return this._request('POST', '/api/recipes/match', { ingredients });
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Meal-plan endpoints (LLM recipe suggester + user selections)
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async getMealPlanWeek() {
    return this._request('GET', '/api/meal-plan/week');
  },

  async addMealPlanEntry(data) {
    return this._request('POST', '/api/meal-plan/entry', data);
  },

  async deleteMealPlanEntry(id) {
    return this._request('DELETE', `/api/meal-plan/entry/${id}`);
  },

  async getMealPlanPool(variant = 0) {
    const query = Number.isFinite(Number(variant)) ? `?variant=${encodeURIComponent(Number(variant))}` : '';
    return this._request('GET', `/api/meal-plan/pool${query}`);
  },

  async nameMealPlanPool(variant = 0) {
    const query = Number.isFinite(Number(variant)) ? `?variant=${encodeURIComponent(Number(variant))}` : '';
    return this._request('POST', `/api/meal-plan/pool/name${query}`, {});
  },

  async supplementMealPlanPool(body) {
    return this._request('POST', '/api/meal-plan/pool/supplement', body);
  },

  async arrangeMealPlan(body) {
    return this._request('POST', '/api/meal-plan/arrange', body);
  },

  async confirmMealPlanDay(date) {
    return this._request('POST', `/api/meal-plan/confirm?date=${encodeURIComponent(date)}`);
  },

  async listSavedRecipes() {
    return this._request('GET', '/api/meal-plan/saved-recipes');
  },

  async deleteSavedRecipe(recipeId) {
    return this._request('DELETE', `/api/meal-plan/saved-recipes/${recipeId}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Meal-engine endpoints (deterministic rule engine)
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async mealEngineLibrary() {
    return this._request('GET', '/api/meal-engine/library');
  },

  async mealEngineAudit() {
    return this._request('GET', '/api/meal-engine/audit');
  },

  async mealEngineExchange() {
    return this._request('GET', '/api/meal-engine/exchange');
  },

  async mealEngineTargets() {
    return this._request('GET', '/api/meal-engine/targets');
  },

  async mealEngineProcurement(start_date = null) {
    return this._request('POST', '/api/meal-engine/procurement', { start_date });
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Fixed-meal endpoints (spec-v1: slots auto-filled every week)
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async listFixedMeals() {
    return this._request('GET', '/api/fixed-meals');
  },

  async createFixedMeal(data) {
    return this._request('POST', '/api/fixed-meals', data);
  },

  async updateFixedMeal(id, data) {
    return this._request('PATCH', `/api/fixed-meals/${id}`, data);
  },

  async deleteFixedMeal(id) {
    return this._request('DELETE', `/api/fixed-meals/${id}`);
  },

  async mealEngineDaily(date = null) {
    const qs = date ? `?date=${encodeURIComponent(date)}` : '';
    return this._request('GET', `/api/meal-engine/daily${qs}`);
  },

  async mealEngineWeekly(end_date = null) {
    const qs = end_date ? `?end_date=${encodeURIComponent(end_date)}` : '';
    return this._request('GET', `/api/meal-engine/weekly${qs}`);
  },

  /* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
     Admin endpoints
     鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
  async adminGetMissingRecipes() {
    return this._request('GET', '/api/admin/missing-recipes');
  },

  async adminUpdateReport(id, status) {
    return this._request('PUT', `/api/admin/missing-recipes/${id}`, { status });
  },

  async adminGetRecipes() {
    return this._request('GET', '/api/admin/recipes');
  },

  async adminCreateRecipe(data) {
    return this._request('POST', '/api/admin/recipes', data);
  },

  async adminUpdateRecipe(id, data) {
    return this._request('PUT', `/api/admin/recipes/${id}`, data);
  },

  async adminDeleteRecipe(id) {
    return this._request('DELETE', `/api/admin/recipes/${id}`);
  },

  async adminGetStats() {
    return this._request('GET', '/api/admin/stats');
  },

  async adminGetUsers() {
    return this._request('GET', '/api/admin/users');
  },

  async adminGetUserDetail(id) {
    return this._request('GET', `/api/admin/users/${id}/detail`);
  },

  async adminGetUserPreferences(id) {
    return this._request('GET', `/api/admin/users/${id}/preferences`);
  },

  async adminUpdateUserPreferences(id, data) {
    return this._request('PUT', `/api/admin/users/${id}/preferences`, data);
  },

  async adminGetLLMQuotas(userId = null) {
    const qs = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
    return this._request('GET', `/api/admin/llm-quotas${qs}`);
  },

  async adminResetLLMQuota(id, data) {
    return this._request('POST', `/api/admin/users/${id}/llm-quota/reset`, data);
  },

  async adminResetAllLLMQuotas(data) {
    return this._request('POST', '/api/admin/llm-quotas/reset', data);
  },

  async adminGetFoodLibrary() {
    return this._request('GET', '/api/admin/food-library');
  },

  async adminGetObservabilityEvents({ limit = 80, event = '', userId = '', logger = '' } = {}) {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    if (event) params.set('event', event);
    if (userId) params.set('user_id', String(userId));
    if (logger) params.set('logger', logger);
    return this._request('GET', `/api/admin/observability/events?${params.toString()}`);
  },

  async adminUpdateUser(id, data) {
    return this._request('PATCH', `/api/admin/users/${id}`, data);
  },

  async adminDeleteUser(id) {
    return this._request('DELETE', `/api/admin/users/${id}`);
  },
};

API._request = async function(method, path, body = null, requiresAuth = true) {
  const context = _buildRequestContext(method, path);

  const fetchOnce = async (requestContext, tokenOverride = undefined) => {
    const headers = _withTracingHeaders({ 'Content-Type': 'application/json' }, requestContext);
    if (requiresAuth) {
      const token = tokenOverride === undefined
        ? localStorage.getItem('ch_access_token')
        : tokenOverride;
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    const opts = { method, headers };
    if (body !== null) opts.body = JSON.stringify(body);
    return fetch(`${API_BASE}${path}`, opts);
  };

  let res;
  try {
    res = await fetchOnce(context);
  } catch (err) {
    const wrapped = new Error('网络错误，请检查连接 / Network error: ' + err.message);
    wrapped.requestId = context.requestId;
    wrapped.journeyId = context.journeyId;
    wrapped.uiAction = context.uiAction;
    wrapped.path = path;
    throw wrapped;
  }

  if (res.status === 401 && requiresAuth) {
    const refreshed = await this._tryRefresh(context);
    if (refreshed) {
      const retryContext = _buildRequestContext(method, path, {
        journeyId: context.journeyId,
        uiAction: context.uiAction,
      });
      try {
        res = await fetchOnce(retryContext, localStorage.getItem('ch_access_token'));
      } catch (err) {
        const wrapped = new Error('网络错误，请检查连接 / Network error: ' + err.message);
        wrapped.requestId = retryContext.requestId;
        wrapped.journeyId = retryContext.journeyId;
        wrapped.uiAction = retryContext.uiAction;
        wrapped.path = path;
        throw wrapped;
      }
    } else {
      localStorage.removeItem('ch_access_token');
      localStorage.removeItem('ch_refresh_token');
      localStorage.removeItem('ch_has_bmr');
      localStorage.removeItem('ch_is_admin');
      const wrapped = new Error('Session expired. Please log in again.');
      wrapped.status = 401;
      wrapped.error = 'session_expired';
      wrapped.requestId = context.requestId;
      wrapped.journeyId = context.journeyId;
      wrapped.uiAction = context.uiAction;
      wrapped.path = path;
      throw wrapped;
    }
  }

  let data;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try { data = await res.json(); } catch { data = {}; }
  } else {
    try { data = await res.text(); } catch { data = null; }
  }

  if (!res.ok) {
    const detail = data && data.detail !== undefined ? data.detail : null;
    const msg = (detail || (data && (data.message || data.error))) || `HTTP ${res.status}`;
    const wrapped = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    wrapped.requestId = res.headers.get('x-request-id') || context.requestId;
    wrapped.journeyId = res.headers.get('x-journey-id') || context.journeyId;
    wrapped.uiAction = context.uiAction;
    wrapped.path = path;
    wrapped.status = res.status;
    wrapped.detail = detail || (data && typeof data === 'object' ? data : null);
    wrapped.error = (detail && detail.error) || (data && data.error) || null;
    throw wrapped;
  }

  return data;
};

API._tryRefresh = async function(parentContext = null) {
  const refreshToken = localStorage.getItem('ch_refresh_token');
  if (!refreshToken) return false;

  const context = _buildRequestContext('POST', '/api/auth/refresh', {
    journeyId: parentContext?.journeyId,
    uiAction: 'auth.refresh',
  });

  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: _withTracingHeaders({ 'Content-Type': 'application/json' }, context),
      body: JSON.stringify({ refresh_token: refreshToken })
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data.access_token) {
      localStorage.setItem('ch_access_token', data.access_token);
      if (data.refresh_token) localStorage.setItem('ch_refresh_token', data.refresh_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
};


/* ============================================================
   display-v2 wiring — agent-backed meal engine
   The functions below override their FastAPI versions and read
   from the health domain through the FastAPI BFF (default) or the
   agent display API directly (dev fallback, ch_display_api_mode).
   Everything not overridden here still uses API_BASE.
   Contract: compass-health-agent/docs/display-interface-plan.md
   ============================================================ */

const AGENT_API_BASE = localStorage.getItem('ch_display_api') || 'http://127.0.0.1:8788';
// M01: the browser reaches the health domain through the authenticated
// FastAPI BFF (/api/domain/*) — direct calls to the Display API bypassed
// JWT user isolation and cross-service tracing. 'direct' remains only as a
// developer fallback (set ch_display_api_mode in localStorage).
const AGENT_API_MODE = localStorage.getItem('ch_display_api_mode') || 'bff';

API._agentRequest = async function(method, path, body = null) {
  const context = _buildRequestContext(method, path);
  let headers = { 'Content-Type': 'application/json' };
  let url;
  if (AGENT_API_MODE === 'bff') {
    // '/api/plan?start=…' → '${API_BASE}/api/domain/plan?start=…'
    url = `${API_BASE}${path.replace(/^\/api\//, '/api/domain/')}`;
    const token = localStorage.getItem('ch_access_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else {
    url = `${AGENT_API_BASE}${path}`;
  }
  headers = _withTracingHeaders(headers, context);

  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === null ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    throw new Error(I18n.lang === 'zh'
      ? (AGENT_API_MODE === 'bff'
          ? '无法连接健康服务（经 FastAPI BFF）— 请确认 backend 与健康领域服务已启动'
          : '无法连接营养引擎显示服务 — 请在 compass-health-agent 目录运行 pnpm serve:display')
      : (AGENT_API_MODE === 'bff'
          ? 'Cannot reach the health domain via the FastAPI BFF — check backend and domain service'
          : 'Cannot reach the agent display API — run `pnpm serve:display` in compass-health-agent'));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.requestId = data.request_id || context.requestId;
    throw err;
  }
  return data;
};

/* ── shared agent-side helpers ── */

API._agentFoodsCache = null;
API._agentFoods = async function() {
  if (!this._agentFoodsCache) {
    const data = await this._agentRequest('GET', '/api/foods');
    this._agentFoodsCache = new Map((data.foods || []).map(f => [f.slug, f]));
  }
  return this._agentFoodsCache;
};

API._agentMonday = function(fromDate) {
  const d = fromDate ? new Date(`${fromDate}T00:00:00`) : new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

API._agentWeekdayLabels = function(dateIso) {
  const day = new Date(`${dateIso}T00:00:00`).getDay();
  return {
    zh: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day],
    en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][day],
  };
};

API._agentIngredientList = function(rawList, foods) {
  return (rawList || []).map(item => {
    const food = foods.get(item.slug);
    return {
      slug: item.slug,
      grams: item.grams,
      name_zh: food ? (food.nameZh || food.name) : null,
      name_en: food ? food.name : null,
    };
  });
};

API._AGENT_METHOD_ZH = {
  stir_fry: '炒', braising: '红烧/卤', steaming: '清蒸',
  boiling: '汆/煮', pan_searing: '香煎', cold_mixing: '凉拌',
};

/* Build the arranged-week shape the weekly menu overview renders, from the
   STORED week (GET /api/plan). Calories come per meal and per day. */
API.getStoredArrangedWeek = async function() {
  const monday = this._agentMonday();
  const [view, profileRes, foods] = await Promise.all([
    this._agentRequest('GET', `/api/plan?start=${monday}&days=7`),
    this._agentRequest('GET', '/api/profile').catch(() => null),
    this._agentFoods(),
  ]);
  const hasEntries = (view.days || []).some(d => (d.entries || []).length > 0);
  if (!hasEntries) return null;
  const calorieTarget = profileRes && profileRes.profile ? profileRes.profile.targetKcal : null;

  const days = view.days.map(day => {
    const meals = {};
    for (const row of day.entries) {
      meals[row.mealType] = {
        name: row.dishName,
        source: row.status === 'planned' ? 'selected' : row.status,
        totals: {
          kcal: Math.round(row.caloriesKcal),
          protein_g: row.proteinGrams,
          carbs_g: row.carbsGrams,
          fat_g: row.fatGrams,
        },
        ingredients: this._agentIngredientList(row.ingredientsJson, foods),
        seasonings: [],
        method_steps: '',
      };
    }
    const labels = this._agentWeekdayLabels(day.date);
    return {
      date: day.date,
      day_type: 'normal',
      day_type_label_zh: labels.zh,
      day_type_label_en: labels.en,
      meals,
      target: { calorie_target: calorieTarget },
      totals: { kcal: day.totals.kcal },
    };
  });

  return {
    start_date: view.startDate,
    days,
    warnings: [],
    micronutrients: {},
    arranged_entry_count: view.days.reduce((n, d) => n + d.entries.length, 0),
  };
};

/* ── pool: dish library as the candidate view ── */

API._agentPoolPayload = async function(variant) {
  const monday = this._agentMonday();
  const [dishes, foods] = await Promise.all([
    this._agentRequest('GET', '/api/dishes'),
    this._agentFoods(),
  ]);
  const toDish = (d, sourceZh, sourceEn) => ({
    slug: d.slug,
    dish_id: d.slug,
    name: d.name,
    name_zh: d.name,
    meal_type: (d.mealTypes || []).includes('breakfast') ? 'breakfast' : 'main',
    totals: {
      kcal: d.nutrition ? d.nutrition.kcal : (d.caloriesKcal ?? 0),
      protein_g: d.nutrition ? d.nutrition.proteinGrams : (d.proteinGrams ?? 0),
      carbs_g: d.nutrition ? d.nutrition.carbsGrams : (d.carbsGrams ?? 0),
      fat_g: d.nutrition ? d.nutrition.fatGrams : (d.fatGrams ?? 0),
    },
    ingredients: this._agentIngredientList(d.ingredients || d.ingredientsJson, foods),
    seasonings: [],
    method_steps: this._AGENT_METHOD_ZH[d.method] || d.method || '',
    source: 'library',
    source_label_zh: sourceZh,
    source_label_en: sourceEn,
  });
  const presets = (dishes.presets || []).map(d => toDish(d, '默认菜谱', 'Default recipes'));
  const users = (dishes.userDishes || []).map(d => toDish(d, '我的菜', 'My dishes'));
  const all = [...presets, ...users];
  const week_skeleton = Array.from({ length: 7 }, (_, i) => {
    const dd = new Date(`${monday}T00:00:00`);
    dd.setDate(dd.getDate() + i);
    const iso = `${dd.getFullYear()}-${String(dd.getMonth() + 1).padStart(2, '0')}-${String(dd.getDate()).padStart(2, '0')}`;
    const labels = this._agentWeekdayLabels(iso);
    return { date: iso, day_type: 'normal', day_type_label_zh: labels.zh, day_type_label_en: labels.en, is_locked: false };
  });
  return {
    pool_tag: `agent:${monday}:${variant || 0}`,
    start_date: monday,
    variant: variant || 0,
    breakfast_dishes: all.filter(d => d.meal_type === 'breakfast'),
    main_dishes: all.filter(d => d.meal_type === 'main'),
    requires_breakfast_pool: true,
    requires_main_pool: true,
    required_slot_counts: { breakfast: 7, lunch: 7, dinner: 7 },
    week_skeleton,
    llm_quota: null,
    warnings: [],
  };
};

API.nameMealPlanPool = function(variant) { return this._agentPoolPayload(variant); };
API.getMealPlanPool = function(variant) { return this._agentPoolPayload(variant); };

/* ── generation: one-shot full-week plan via the agent ── */

API.arrangeMealPlan = async function(_body) {
  const monday = this._agentMonday();
  const result = await this._agentRequest('POST', '/api/plan/generate', { startDate: monday });
  if (result.status === 'blocked') {
    const reason = result.cannotSatisfy ? result.cannotSatisfy.reason : 'blocked';
    const suggestions = result.cannotSatisfy ? (result.cannotSatisfy.suggestions || []) : [];
    throw new Error([reason, ...suggestions].join(' · '));
  }
  const [profileRes, foods] = await Promise.all([
    this._agentRequest('GET', '/api/profile').catch(() => null),
    this._agentFoods(),
  ]);
  const calorieTarget = profileRes && profileRes.profile ? profileRes.profile.targetKcal : null;
  const notices = [
    ...(result.pool && result.pool.fatBudgetNotice ? [result.pool.fatBudgetNotice] : []),
    ...((result.pool && result.pool.poolNotices) || []),
  ];

  const days = (result.plan.days || []).map(day => {
    const meals = {};
    for (const entry of day.meals) {
      const parts = [
        ...(entry.dish.ingredients || []),
        ...((entry.side && entry.side.ingredients) || []),
        ...((entry.proteinTopUps || []).flatMap(tp => tp.ingredients || [])),
        ...(entry.staple ? [entry.staple] : []),
      ];
      meals[entry.mealType] = {
        name: entry.side ? `${entry.dish.name} + ${entry.side.name}` : entry.dish.name,
        source: 'selected',
        totals: {
          kcal: Math.round(entry.nutrition.kcal),
          protein_g: entry.nutrition.proteinGrams,
          carbs_g: entry.nutrition.carbsGrams,
          fat_g: entry.nutrition.fatGrams,
        },
        ingredients: this._agentIngredientList(parts, foods),
        seasonings: [],
        method_steps: this._AGENT_METHOD_ZH[entry.dish.method] || entry.dish.method || '',
      };
    }
    const labels = this._agentWeekdayLabels(day.date);
    return {
      date: day.date,
      day_type: 'normal',
      day_type_label_zh: labels.zh,
      day_type_label_en: labels.en,
      meals,
      target: { calorie_target: calorieTarget },
      totals: { kcal: Math.round(day.totals.kcal) },
    };
  });

  return {
    start_date: result.plan.startDate,
    days,
    warnings: notices,
    micronutrients: {},
    arranged_entry_count: (result.plan.entries || []).length,
  };
};

/* ── grocery list ── */

API._AGENT_CATEGORY_ZH = {
  meat: '肉类', poultry: '禽类', seafood: '海鲜', vegetable: '蔬菜',
  grain: '谷物', legume: '豆类', dairy: '乳制品', nut: '坚果',
  fruit: '水果', egg: '蛋类', oil: '油脂', starch: '淀粉',
  tuber: '薯类', mushroom: '菌菇', seaweed: '海藻', bread: '面包', other: '其他',
};

API.mealEngineProcurement = async function(startDate) {
  const start = startDate || this._agentMonday();
  const [proc, foods] = await Promise.all([
    this._agentRequest('GET', `/api/procurement?start=${start}&days=7`),
    this._agentFoods(),
  ]);
  const items = proc.items || [];
  if (items.length === 0) {
    return {
      feasibility: 'not_closed_loop',
      message_zh: '本周还没有已排菜单 — 先在「餐单」页生成一周菜单。',
      message_en: 'Nothing planned for this week yet — generate a weekly plan first.',
    };
  }
  const byCategory = new Map();
  for (const item of items) {
    const food = foods.get(item.slug);
    const category = (food && food.category) || 'other';
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push({
      slug: item.slug,
      name_zh: food ? (food.nameZh || food.name) : item.slug,
      name_en: food ? food.name : item.slug,
      meal_count: item.dishCount,
      planned_g: item.totalGrams,
      recommended_g: item.bufferedGrams,
      is_key_food: false,
      replaceable: false,
    });
  }
  return {
    feasibility: 'ok',
    total_slugs: items.length,
    total_planned_g: items.reduce((sum, item) => sum + item.totalGrams, 0),
    warnings: [],
    groups: [...byCategory.entries()].map(([category, rows]) => ({
      label_zh: this._AGENT_CATEGORY_ZH[category] || category,
      label_en: category.charAt(0).toUpperCase() + category.slice(1),
      rows,
    })),
  };
};

/* ── fixed food items (was: fixed meals) ── */

API.listFixedMeals = async function() {
  const foods = await this._agentFoods();
  const items = [...foods.values()].map((food, index) => ({
    id: index + 1,
    recipe_name: food.nameZh || food.name || food.slug,
    custom_name: null,
    weekday: null,
    meal_type: 'food_item',
    portion_g: 100,
    calories: food.kcalPer100g,
    protein_g: food.proteinGramsPer100g,
    carbs_g: food.carbsGramsPer100g,
    fat_g: food.fatGramsPer100g,
  }));
  return { items };
};

API._agentReadOnly = function() {
  return Promise.reject(new Error(I18n.lang === 'zh'
    ? '固定食材来自营养引擎的食材库,在 compass-health-agent 的 seed 数据中维护'
    : 'Fixed food items come from the agent seed catalog; edit them in compass-health-agent'));
};
API.createFixedMeal = function() { return this._agentReadOnly(); };
API.updateFixedMeal = function() { return this._agentReadOnly(); };
API.deleteFixedMeal = function() { return this._agentReadOnly(); };

/* ── default recipes (was: saved recipes) ── */

API.listSavedRecipes = async function() {
  const [dishes, foods] = await Promise.all([
    this._agentRequest('GET', '/api/dishes'),
    this._agentFoods(),
  ]);
  const zh = I18n.lang === 'zh';
  const mealTypeLabel = types => (types || [])
    .map(mt => zh
      ? ({ breakfast: '早餐', lunch: '午餐', dinner: '晚餐' })[mt] || mt
      : mt)
    .join(' / ');
  const items = (dishes.presets || []).map(d => ({
    saved_at: '',
    recipe: {
      id: d.slug,
      name: d.name,
      calories: d.nutrition.kcal,
      protein_g: d.nutrition.proteinGrams,
      carbs_g: d.nutrition.carbsGrams,
      fat_g: d.nutrition.fatGrams,
      meal_types: mealTypeLabel(d.mealTypes),
      ingredients: this._agentIngredientList(d.ingredients, foods),
      steps: d.method ? [this._AGENT_METHOD_ZH[d.method] || d.method] : [],
    },
  }));
  return { cap: items.length, count: items.length, items };
};

API.deleteSavedRecipe = function() {
  return Promise.reject(new Error(I18n.lang === 'zh'
    ? '默认菜谱不可删除 — 它们由营养引擎的预设菜库提供'
    : 'Default recipes cannot be deleted — they come from the agent preset library'));
};

/* ── execution feedback (weekly review) ── */

API.mealEngineDaily = async function() {
  const d = new Date();
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const summary = await this._agentRequest('GET', `/api/summary?date=${date}`);
  const rate = (actual, target) => (target > 0 ? actual / target : 0);
  const status = r => (r > 1.1 ? 'over' : r < 0.9 ? 'under' : 'on_track');
  const rates = {
    kcal: rate(summary.eaten.kcal, summary.target.kcal),
    protein: rate(summary.eaten.proteinGrams, summary.target.proteinGrams),
    carbs: rate(summary.eaten.carbsGrams, summary.target.carbsGrams),
    fat: rate(summary.eaten.fatGrams, summary.target.fatGrams),
  };
  return {
    has_bmr_profile: summary.target.kcal > 0,
    date: summary.date,
    target: {
      kcal: summary.target.kcal,
      protein_g: summary.target.proteinGrams,
      carbs_g: summary.target.carbsGrams,
      fat_g: summary.target.fatGrams,
    },
    actual: {
      kcal: summary.eaten.kcal,
      protein_g: summary.eaten.proteinGrams,
      carbs_g: summary.eaten.carbsGrams,
      fat_g: summary.eaten.fatGrams,
    },
    achievement_rate: rates,
    status: {
      kcal: status(rates.kcal),
      protein: status(rates.protein),
      carbs: status(rates.carbs),
      fat: status(rates.fat),
    },
    exercise_kcal: summary.exercise.kcalBurned,
    net_kcal: summary.eaten.kcal - summary.exercise.kcalBurned,
    notes: [],
  };
};

API.mealEngineWeekly = async function() {
  const d = new Date();
  const endDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const [report, profileRes] = await Promise.all([
    this._agentRequest('GET', `/api/report?endDate=${endDate}`),
    this._agentRequest('GET', '/api/profile').catch(() => null),
  ]);
  const profile = profileRes && profileRes.profile ? profileRes.profile : null;
  const kcalTarget = profile ? profile.targetKcal : 0;
  const proteinTarget = profile ? profile.proteinTargetGrams : 0;
  const avgProteinG = report.averageKcal > 0
    ? (report.averageKcal * (report.macroSplit.proteinPct / 100)) / 4
    : 0;
  const adjustments = [
    { kind: 'calorie_up', message_zh: report.weeklyBudgetLine, message_en: report.weeklyBudgetLine },
    ...(report.suggestions || []).map(s => ({ kind: 'calorie_up', message_zh: s, message_en: s })),
  ];
  return {
    has_bmr_profile: profile !== null,
    averages: {
      kcal: Math.round(report.averageKcal),
      protein_g: Math.round(avgProteinG * 10) / 10,
      kcal_achievement: kcalTarget > 0 ? report.averageKcal / kcalTarget : 0,
      protein_achievement: proteinTarget > 0 ? avgProteinG / proteinTarget : 0,
    },
    weight_trend_kg: null,
    adjustments,
    message_zh: report.weeklyBudgetLine,
    message_en: report.weeklyBudgetLine,
  };
};

/* ── homepage weekly plan card (dashboard) ── */

API._agentWeekKcal = new Map();

API.getMealPlanWeek = async function() {
  const monday = this._agentMonday();
  const view = await this._agentRequest('GET', `/api/plan?start=${monday}&days=7`);
  const d = new Date();
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  this._agentWeekKcal = new Map();
  const days = (view.days || []).map(day => {
    const meals = {};
    for (const row of day.entries || []) {
      const refId = `agent:${row.id}`;
      this._agentWeekKcal.set(refId, Math.round(row.caloriesKcal));
      meals[row.mealType] = {
        recipe: { name: row.dishName },
        recipe_id: refId,
        custom_name: null,
      };
    }
    return { date: day.date, meals };
  });
  return { today, days };
};

/* The dashboard resolves per-meal kcal through getRecipe(recipe_id); serve
   agent-backed ids from the week cache and pass everything else through. */
API._origGetRecipe = API.getRecipe.bind(API);
API.getRecipe = function(recipeId) {
  if (typeof recipeId === 'string' && recipeId.startsWith('agent:')) {
    return Promise.resolve({ calories: this._agentWeekKcal.get(recipeId) || 0 });
  }
  return this._origGetRecipe(recipeId);
};
