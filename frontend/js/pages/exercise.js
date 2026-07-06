/* ============================================================
   Compass Health — pages/exercise.js
   Exercise logging page
   ============================================================ */

const ExercisePage = {
  async render() {
    const el = document.getElementById('page-exercise');
    if (!el) return;
    const t = k => I18n.t(k);

    const types = ['running','walking','cycling','swimming','gym','yoga','hiit','other'];

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('exercise.title')}</h2></div>
      </div>
      <div class="grid-2" style="gap:24px">
        <div>
          <div class="card">
            <div class="card-title">${t('exercise.add')}</div>
            <div class="form-group">
              <label>${t('exercise.type')}</label>
              <select id="ex-type" class="form-control">
                <option value="">--</option>
                ${types.map(tp => `<option value="${tp}">${t('exercise.types.' + tp)}</option>`).join('')}
              </select>
              <div class="form-error" id="err-ex-type"></div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>${t('exercise.duration')}</label>
                <input id="ex-duration" type="number" min="1" max="600" class="form-control" placeholder="30">
                <div class="form-error" id="err-ex-duration"></div>
              </div>
              <div class="form-group">
                <label>${t('exercise.calories')}</label>
                <input id="ex-calories" type="number" min="1" max="5000" class="form-control" placeholder="200">
                <div class="form-error" id="err-ex-cal"></div>
              </div>
            </div>
            <div class="form-group">
              <label>${t('exercise.notes')}</label>
              <input id="ex-notes" type="text" class="form-control" placeholder="${I18n.lang === 'zh' ? '可选备注' : 'Optional notes'}">
            </div>
            <button class="btn btn-primary btn-full" id="ex-log-btn">${t('exercise.log_btn')}</button>
          </div>
        </div>

        <div>
          <!-- Summary -->
          <div class="grid-2" style="margin-bottom:16px">
            <div class="card">
              <div class="card-title">${t('exercise.total_cal')}</div>
              <div class="card-value" id="ex-total-cal">0</div>
              <div class="card-sub">kcal</div>
            </div>
            <div class="card">
              <div class="card-title">${t('exercise.total_min')}</div>
              <div class="card-value" id="ex-total-min">0</div>
              <div class="card-sub">${t('common.min')}</div>
            </div>
          </div>
          <!-- Log list -->
          <div class="card">
            <div class="card-title">${t('exercise.title')}</div>
            <div class="log-list" id="ex-log-list">
              <div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${t('common.loading')}</div>
            </div>
          </div>
        </div>
      </div>`;

    document.getElementById('ex-log-btn').onclick = () => this._submit();
    await this._loadData();
  },

  async _loadData() {
    try {
      const data = await API.getExerciseToday();
      document.getElementById('ex-total-cal').textContent = data.total_calories || 0;
      document.getElementById('ex-total-min').textContent = data.total_minutes || 0;
      this._renderLogs(data.logs);
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _renderLogs(logs) {
    const container = document.getElementById('ex-log-list');
    if (!container) return;
    if (!logs || !logs.length) {
      container.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${I18n.t('common.no_data')}</div>`;
      return;
    }
    const t = k => I18n.t(k);
    container.innerHTML = logs.map(l => {
      const time = new Date(l.logged_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return `
        <div class="log-item">
          <div class="log-info">
            <div><strong>${this._esc(t('exercise.types.' + l.exercise_type) || l.exercise_type)}</strong></div>
            <span class="log-value">${l.calories_burned} kcal</span>
            <span class="log-time">${l.duration_min} ${t('common.min')} · ${time}</span>
            ${l.notes ? `<div style="font-size:0.74rem;color:var(--text-3)">${this._esc(l.notes)}</div>` : ''}
          </div>
          <button class="log-delete" onclick="ExercisePage._deleteLog(${l.id})">✕</button>
        </div>`;
    }).join('');
  },

  async _submit() {
    const type = document.getElementById('ex-type').value;
    const duration = parseInt(document.getElementById('ex-duration').value);
    const calories = parseInt(document.getElementById('ex-calories').value);
    const notes = document.getElementById('ex-notes').value.trim();

    let ok = true;
    ['err-ex-type','err-ex-duration','err-ex-cal'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '';
    });

    if (!type) { document.getElementById('err-ex-type').textContent = I18n.lang === 'zh' ? '请选择运动类型' : 'Select exercise type'; ok = false; }
    if (!duration || duration < 1) { document.getElementById('err-ex-duration').textContent = I18n.lang === 'zh' ? '请输入有效时长' : 'Enter valid duration'; ok = false; }
    if (!calories || calories < 1) { document.getElementById('err-ex-cal').textContent = I18n.lang === 'zh' ? '请输入热量消耗' : 'Enter calories burned'; ok = false; }
    if (!ok) return;

    const btn = document.getElementById('ex-log-btn');
    btn.disabled = true;
    try {
      await API.logExercise({ exercise_type: type, duration_min: duration, calories_burned: calories, notes: notes || null });
      App.showToast(I18n.lang === 'zh' ? '运动记录已保存' : 'Exercise logged', 'success');
      document.getElementById('ex-type').value = '';
      document.getElementById('ex-duration').value = '';
      document.getElementById('ex-calories').value = '';
      document.getElementById('ex-notes').value = '';
      await this._loadData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
    btn.disabled = false;
  },

  async _deleteLog(id) {
    App.openModal(
      I18n.t('common.confirm_delete'),
      `<p style="font-size:0.9rem;color:var(--text-2)">${I18n.lang === 'zh' ? '删除该条运动记录？' : 'Delete this exercise log?'}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-danger" onclick="ExercisePage._confirmDelete(${id})">${I18n.t('common.delete')}</button>`
    );
  },

  async _confirmDelete(id) {
    App.closeModal();
    try {
      await API.deleteExerciseLog(id);
      App.showToast(I18n.lang === 'zh' ? '已删除' : 'Deleted', 'success');
      await this._loadData();
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
};
