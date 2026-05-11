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
