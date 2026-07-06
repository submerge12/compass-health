/* ============================================================
   Compass Health — pages/water.js
   Water intake tracking page
   ============================================================ */

const WaterPage = {
  _data: null,

  async render() {
    const el = document.getElementById('page-water');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('water.title')}</h2></div>
      </div>
      <div class="grid-2" style="gap:24px">
        <div>
          <!-- Ring progress -->
          <div class="card" style="text-align:center">
            <div class="card-title">${t('dash.water_today')}</div>
            <div class="ring-wrap">
              <svg class="ring-svg" width="140" height="140" viewBox="0 0 140 140">
                <circle class="ring-track" cx="70" cy="70" r="54"/>
                <circle class="ring-fill" id="ring-fill" cx="70" cy="70" r="54"
                  stroke-dasharray="339.3" stroke-dashoffset="339.3"/>
              </svg>
            </div>
            <div class="ring-label">
              <div class="big" id="water-total">0</div>
              <div class="unit">ml / <span id="water-goal">2000</span> ml</div>
            </div>
            <div style="margin-top:8px;font-size:0.82rem;color:var(--text-3)">
              ${t('water.remaining')}: <span id="water-remaining">2000</span> ml
            </div>
          </div>

          <!-- Quick add -->
          <div class="card" style="margin-top:16px">
            <div class="card-title">${t('water.add')}</div>
            <div class="quick-btns">
              <button class="quick-btn" data-ml="100">100 ml</button>
              <button class="quick-btn" data-ml="200">200 ml</button>
              <button class="quick-btn" data-ml="250">250 ml</button>
              <button class="quick-btn" data-ml="500">500 ml</button>
            </div>
            <div style="display:flex;gap:10px;align-items:flex-end">
              <div class="form-group" style="flex:1;margin-bottom:0">
                <label>${t('water.amount')}</label>
                <input id="water-custom" type="number" min="1" max="2000" class="form-control" placeholder="150">
              </div>
              <button class="btn btn-primary" id="water-log-btn">${t('water.log_btn')}</button>
            </div>
          </div>
        </div>

        <div>
          <!-- Log list -->
          <div class="card">
            <div class="card-title">${t('water.history')}</div>
            <div class="log-list" id="water-log-list">
              <div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${t('common.loading')}</div>
            </div>
          </div>

          <!-- 7-day chart -->
          <div class="card" style="margin-top:16px">
            <div class="card-title">7-day history</div>
            <div class="bar-chart" id="water-bar-chart"></div>
          </div>
        </div>
      </div>`;

    // Quick add buttons
    document.querySelectorAll('.quick-btn[data-ml]').forEach(btn => {
      btn.addEventListener('click', () => this._logWater(parseInt(btn.dataset.ml)));
    });

    // Custom log
    document.getElementById('water-log-btn').onclick = () => {
      const val = parseInt(document.getElementById('water-custom').value);
      if (!val || val < 1) return App.showToast(I18n.lang === 'zh' ? '请输入有效饮水量' : 'Enter a valid amount', 'error');
      this._logWater(val);
    };

    await this._loadData();
  },

  async _loadData() {
    try {
      const [today, history] = await Promise.all([API.getWaterToday(), API.getWaterHistory(7)]);
      this._data = today;
      this._updateRing(today);
      this._renderLogs(today.logs);
      this._renderChart(history);
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _updateRing(data) {
    const total = data.total_ml || 0;
    const goal = data.goal_ml || 2000;
    const pct = Math.min(1, total / goal);
    const circ = 339.3;
    const offset = circ * (1 - pct);

    const fill = document.getElementById('ring-fill');
    if (fill) fill.setAttribute('stroke-dashoffset', offset.toFixed(1));

    const totalEl = document.getElementById('water-total');
    if (totalEl) totalEl.textContent = total;

    const goalEl = document.getElementById('water-goal');
    if (goalEl) goalEl.textContent = goal;

    const remEl = document.getElementById('water-remaining');
    if (remEl) remEl.textContent = Math.max(0, goal - total);
  },

  _renderLogs(logs) {
    const container = document.getElementById('water-log-list');
    if (!container) return;
    if (!logs || !logs.length) {
      container.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${I18n.t('common.no_data')}</div>`;
      return;
    }
    container.innerHTML = logs.map(l => {
      const time = new Date(l.logged_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return `
        <div class="log-item">
          <div class="log-info">
            <span class="log-value">${l.amount_ml} ml</span>
            <span class="log-time">${time}</span>
          </div>
          <button class="log-delete" onclick="WaterPage._deleteLog(${l.id})">✕</button>
        </div>`;
    }).join('');
  },

  _renderChart(history) {
    const container = document.getElementById('water-bar-chart');
    if (!container || !history) return;
    const max = Math.max(...history.map(d => d.total_ml), 1);
    const todayStr = this._todayDateString();
    container.innerHTML = history.map(d => {
      const h = Math.round((d.total_ml / max) * 80);
      const label = d.date.slice(5);
      const isToday = d.date === todayStr;
      return `
        <div class="bar-col ${isToday ? 'today' : ''}">
          <div class="bar" style="height:${h}px" title="${d.total_ml} ml"></div>
          <div class="bar-label">${label}</div>
        </div>`;
    }).join('');
  },

  _todayDateString() {
    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  },

  async _logWater(amount) {
    try {
      await API.logWater(amount);
      App.showToast(`+${amount} ml`, 'success');
      await this._loadData();
      document.getElementById('water-custom').value = '';
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _deleteLog(id) {
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">${I18n.lang === 'zh' ? '删除该条饮水记录？' : 'Delete this water log entry?'}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="WaterPage._confirmDelete(${id})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmDelete(id) {
    App.closeModal();
    try {
      await API.deleteWaterLog(id);
      App.showToast(I18n.lang === 'zh' ? '已删除' : 'Deleted', 'success');
      await this._loadData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  }
};
