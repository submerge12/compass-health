/* ============================================================
   Compass Health — pages/condition.js
   Physical condition tracking page
   ============================================================ */

const ConditionPage = {
  _selectedMood: null,

  async render() {
    const el = document.getElementById('page-condition');
    if (!el) return;
    const t = k => I18n.t(k);
    const moods = ['😞','😐','🙂','😊','🤩'];

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('condition.title')}</h2></div>
      </div>
      <div class="card" style="margin-bottom:16px">
        <div class="card-title">${t('condition.target_weight_title')}</div>
        <div class="form-row" style="align-items:flex-end;gap:10px">
          <div class="form-group" style="flex:1">
            <label>${t('condition.target_weight')}</label>
            <input id="cond-target-weight" type="number" step="0.1" min="20" max="300" class="form-control" placeholder="65.0">
          </div>
          <button class="btn btn-primary" id="cond-target-weight-save">${t('common.save')}</button>
        </div>
        <div style="font-size:0.78rem;color:var(--text-3);margin-top:4px">${t('condition.target_weight_hint')}</div>
      </div>
      <div class="grid-2" style="gap:24px">
        <div>
          <div class="card">
            <div class="card-title">${t('condition.log')}</div>
            <div class="form-row">
              <div class="form-group">
                <label>${t('condition.weight')}</label>
                <input id="cond-weight" type="number" step="0.1" min="30" max="300" class="form-control" placeholder="65.5">
              </div>
              <div class="form-group">
                <label>${t('condition.heart_rate')}</label>
                <input id="cond-hr" type="number" min="30" max="220" class="form-control" placeholder="72">
              </div>
            </div>
            <div class="form-group">
              <label>${t('condition.bp')}</label>
              <div class="form-row">
                <input id="cond-sys" type="number" min="50" max="250" class="form-control" placeholder="${t('condition.bp_sys')}">
                <input id="cond-dia" type="number" min="30" max="150" class="form-control" placeholder="${t('condition.bp_dia')}">
              </div>
            </div>
            <div class="form-group">
              <label>${t('condition.sleep')}</label>
              <input id="cond-sleep" type="number" step="0.5" min="0" max="24" class="form-control" placeholder="7.5">
            </div>
            <div class="form-group">
              <label>${t('condition.mood')}</label>
              <div class="mood-picker" id="mood-picker">
                ${moods.map((m, i) => `<div class="mood-option" data-mood="${i+1}" title="${i+1}">${m}</div>`).join('')}
              </div>
            </div>
            <div class="form-group">
              <label>${t('condition.notes')}</label>
              <input id="cond-notes" type="text" class="form-control" placeholder="${I18n.lang === 'zh' ? '可选备注' : 'Optional notes'}">
            </div>
            <button class="btn btn-primary btn-full" id="cond-save-btn">${t('condition.save')}</button>
          </div>
        </div>

        <div>
          <div class="card" style="margin-bottom:16px">
            <div class="card-title">${I18n.lang === 'zh' ? '今日数据' : "Today's Record"}</div>
            <div id="cond-today-content" style="color:var(--text-3);font-size:0.84rem;padding:8px 0">${t('common.loading')}</div>
          </div>
          <div class="card">
            <div class="card-title">${t('condition.history')}</div>
            <div style="overflow-x:auto">
              <table class="stats-table">
                <thead>
                  <tr>
                    <th>${I18n.lang === 'zh' ? '日期' : 'Date'}</th>
                    <th>${I18n.lang === 'zh' ? '体重' : 'Weight'}</th>
                    <th>${I18n.lang === 'zh' ? '血压' : 'BP'}</th>
                    <th>${I18n.lang === 'zh' ? '睡眠' : 'Sleep'}</th>
                    <th>${I18n.lang === 'zh' ? '心情' : 'Mood'}</th>
                  </tr>
                </thead>
                <tbody id="cond-history-body">
                  <tr><td colspan="5" style="text-align:center;color:var(--text-3)">${t('common.loading')}</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>`;

    this._selectedMood = null;
    document.querySelectorAll('.mood-option').forEach(opt => {
      opt.addEventListener('click', () => {
        document.querySelectorAll('.mood-option').forEach(o => o.classList.remove('selected'));
        opt.classList.add('selected');
        this._selectedMood = parseInt(opt.dataset.mood);
      });
    });

    document.getElementById('cond-save-btn').onclick = () => this._submit();
    document.getElementById('cond-target-weight-save').onclick = () => this._saveTargetWeight();
    await this._loadData();
  },

  async _loadData() {
    try {
      const [today, history, me] = await Promise.all([
        API.getConditionToday(),
        API.getConditionHistory(7),
        API.getMe(),
      ]);
      this._renderToday(today);
      this._renderHistory(history);
      if (today) this._prefill(today);
      if (me && me.target_weight_kg != null) {
        document.getElementById('cond-target-weight').value = me.target_weight_kg;
      }
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  async _saveTargetWeight() {
    const raw = document.getElementById('cond-target-weight').value.trim();
    const btn = document.getElementById('cond-target-weight-save');
    const isZh = I18n.lang === 'zh';
    let val = null;
    if (raw) {
      val = parseFloat(raw);
      if (isNaN(val) || val < 20 || val > 300) {
        App.showToast(isZh ? '请输入有效体重（20–300 kg）' : 'Enter a valid weight (20–300 kg)', 'error');
        return;
      }
    }
    btn.disabled = true;
    try {
      await API.updateTargetWeight(val);
      App.showToast(isZh ? '目标体重已保存' : 'Target weight saved', 'success');
    } catch (err) {
      App.showToast(err.message, 'error');
    }
    btn.disabled = false;
  },

  _prefill(data) {
    if (data.weight_kg)   document.getElementById('cond-weight').value = data.weight_kg;
    if (data.bp_systolic) document.getElementById('cond-sys').value = data.bp_systolic;
    if (data.bp_diastolic) document.getElementById('cond-dia').value = data.bp_diastolic;
    if (data.heart_rate)  document.getElementById('cond-hr').value = data.heart_rate;
    if (data.sleep_hours) document.getElementById('cond-sleep').value = data.sleep_hours;
    if (data.notes)       document.getElementById('cond-notes').value = data.notes;
    if (data.mood) {
      this._selectedMood = data.mood;
      document.querySelector(`.mood-option[data-mood="${data.mood}"]`)?.classList.add('selected');
    }
  },

  _renderToday(data) {
    const el = document.getElementById('cond-today-content');
    if (!el) return;
    if (!data) { el.textContent = I18n.lang === 'zh' ? '今日暂无记录' : 'No data logged today'; return; }
    const rows = [
      data.weight_kg != null ? [I18n.lang === 'zh' ? '体重' : 'Weight', data.weight_kg + ' kg'] : null,
      (data.bp_systolic != null) ? [I18n.lang === 'zh' ? '血压' : 'BP', `${data.bp_systolic}/${data.bp_diastolic} mmHg`] : null,
      data.heart_rate != null ? [I18n.lang === 'zh' ? '心率' : 'HR', data.heart_rate + ' bpm'] : null,
      data.sleep_hours != null ? [I18n.lang === 'zh' ? '睡眠' : 'Sleep', data.sleep_hours + ' h'] : null,
    ].filter(Boolean);
    el.innerHTML = rows.length
      ? `<table class="stats-table">${rows.map(([k,v]) => `<tr><td>${k}</td><td><strong>${v}</strong></td></tr>`).join('')}</table>`
      : (I18n.lang === 'zh' ? '今日暂无记录' : 'No data logged today');
  },

  _renderHistory(history) {
    const tbody = document.getElementById('cond-history-body');
    if (!tbody || !history) return;
    if (!history.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-3)">${I18n.t('common.no_data')}</td></tr>`;
      return;
    }
    // P0-8: SQLite reads are a LEGACY ARCHIVE view — not current authority.
    const archiveNote = `<tr><td colspan="5" style="text-align:center;color:var(--text-3);font-size:12px">⚠ 历史归档（旧数据库）— 非当前权威数据 / legacy archive</td></tr>`;
    const moods = ['😞','😐','🙂','😊','🤩'];
    tbody.innerHTML = [...history].reverse().slice(0, 7).map(r => `
      <tr>
        <td>${r.date}</td>
        <td>${r.weight_kg != null ? r.weight_kg + ' kg' : '—'}</td>
        <td>${r.bp_systolic != null ? r.bp_systolic + '/' + r.bp_diastolic : '—'}</td>
        <td>${r.sleep_hours != null ? r.sleep_hours + ' h' : '—'}</td>
        <td>${r.mood != null ? moods[r.mood - 1] : '—'}</td>
      </tr>`).join('') + archiveNote;
  },

  async _submit() {
    const payload = {};
    const w     = parseFloat(document.getElementById('cond-weight').value);
    const sys   = parseInt(document.getElementById('cond-sys').value);
    const dia   = parseInt(document.getElementById('cond-dia').value);
    const hr    = parseInt(document.getElementById('cond-hr').value);
    const sleep = parseFloat(document.getElementById('cond-sleep').value);
    const notes = document.getElementById('cond-notes').value.trim();

    if (!isNaN(w) && w > 0) payload.weight_kg = w;
    if (!isNaN(sys) && sys > 0) payload.bp_systolic = sys;
    if (!isNaN(dia) && dia > 0) payload.bp_diastolic = dia;
    if (!isNaN(hr) && hr > 0) payload.heart_rate = hr;
    if (!isNaN(sleep) && sleep >= 0) payload.sleep_hours = sleep;
    if (this._selectedMood) payload.mood = this._selectedMood;
    if (notes) payload.notes = notes;

    if (!Object.keys(payload).length) {
      App.showToast(I18n.lang === 'zh' ? '请至少输入一项数据' : 'Enter at least one value', 'error');
      return;
    }

    const btn = document.getElementById('cond-save-btn');
    btn.disabled = true;
    try {
      await API.logCondition(payload);
      App.showToast(I18n.lang === 'zh' ? '身体状态已保存' : 'Physical condition saved', 'success');
      await this._loadData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
    btn.disabled = false;
  }
};
