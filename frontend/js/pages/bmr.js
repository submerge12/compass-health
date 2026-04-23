/* ============================================================
   Compass Health — pages/bmr.js
   3-step BMR wizard
   ============================================================ */

const BMRPage = {
  _step: 1,
  _data: {},

  render() {
    const container = document.getElementById('bmr-container');
    if (!container) return;
    this._step = 1;
    this._data = {};
    container.innerHTML = `
      <div class="bmr-card">
        <div class="bmr-steps">
          <div class="bmr-step active" id="step-bar-1"></div>
          <div class="bmr-step" id="step-bar-2"></div>
          <div class="bmr-step" id="step-bar-3"></div>
        </div>
        <div id="bmr-step-content"></div>
      </div>`;
    this._showStep1();
    I18n.apply();
  },

  _updateBars(step) {
    [1, 2, 3].forEach(i => {
      const bar = document.getElementById(`step-bar-${i}`);
      if (!bar) return;
      bar.className = 'bmr-step' + (i < step ? ' done' : i === step ? ' active' : '');
    });
  },

  _showStep1() {
    this._updateBars(1);
    const t = k => I18n.t(k);
    document.getElementById('bmr-step-content').innerHTML = `
      <div class="step-label">${t('bmr.step1')}</div>
      <h2 class="bmr-title">${t('bmr.title')}</h2>
      <p class="bmr-subtitle">${t('bmr.subtitle')}</p>
      <div class="form-group">
        <label>${t('bmr.age')}</label>
        <input id="bmr-age" type="number" min="10" max="120" class="form-control" placeholder="25" value="${this._data.age || ''}">
        <div class="form-error" id="err-age"></div>
      </div>
      <div class="form-group">
        <label>${t('bmr.gender')}</label>
        <select id="bmr-gender" class="form-control">
          <option value="">--</option>
          <option value="male" ${this._data.gender === 'male' ? 'selected' : ''}>${t('bmr.gender_male')}</option>
          <option value="female" ${this._data.gender === 'female' ? 'selected' : ''}>${t('bmr.gender_female')}</option>
        </select>
        <div class="form-error" id="err-gender"></div>
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:24px">
        <button class="btn btn-primary" id="s1-next">${t('bmr.next')}</button>
      </div>`;
    document.getElementById('s1-next').onclick = () => {
      const age = parseInt(document.getElementById('bmr-age').value);
      const gender = document.getElementById('bmr-gender').value;
      let ok = true;
      document.getElementById('err-age').textContent = '';
      document.getElementById('err-gender').textContent = '';
      if (!age || age < 10 || age > 120) { document.getElementById('err-age').textContent = I18n.lang === 'zh' ? '请输入10-120之间的年龄' : 'Age must be 10-120'; ok = false; }
      if (!gender) { document.getElementById('err-gender').textContent = I18n.lang === 'zh' ? '请选择性别' : 'Please select gender'; ok = false; }
      if (!ok) return;
      this._data.age = age; this._data.gender = gender;
      this._showStep2();
    };
  },

  _showStep2() {
    this._updateBars(2);
    const t = k => I18n.t(k);
    document.getElementById('bmr-step-content').innerHTML = `
      <div class="step-label">${t('bmr.step2')}</div>
      <h2 class="bmr-title">${t('bmr.title')}</h2>
      <p class="bmr-subtitle">${t('bmr.subtitle')}</p>
      <div class="form-row">
        <div class="form-group">
          <label>${t('bmr.height')}</label>
          <input id="bmr-height" type="number" min="100" max="250" step="0.1" class="form-control" placeholder="170" value="${this._data.height_cm || ''}">
          <div class="form-error" id="err-height"></div>
        </div>
        <div class="form-group">
          <label>${t('bmr.weight')}</label>
          <input id="bmr-weight" type="number" min="30" max="300" step="0.1" class="form-control" placeholder="65" value="${this._data.weight_kg || ''}">
          <div class="form-error" id="err-weight"></div>
        </div>
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:24px">
        <button class="btn btn-ghost" id="s2-back">${t('bmr.back')}</button>
        <button class="btn btn-primary" id="s2-next">${t('bmr.next')}</button>
      </div>`;
    document.getElementById('s2-back').onclick = () => this._showStep1();
    document.getElementById('s2-next').onclick = () => {
      const h = parseFloat(document.getElementById('bmr-height').value);
      const w = parseFloat(document.getElementById('bmr-weight').value);
      let ok = true;
      document.getElementById('err-height').textContent = '';
      document.getElementById('err-weight').textContent = '';
      if (!h || h < 100 || h > 250) { document.getElementById('err-height').textContent = I18n.lang === 'zh' ? '请输入有效身高(100-250cm)' : 'Height must be 100-250 cm'; ok = false; }
      if (!w || w < 30 || w > 300) { document.getElementById('err-weight').textContent = I18n.lang === 'zh' ? '请输入有效体重(30-300kg)' : 'Weight must be 30-300 kg'; ok = false; }
      if (!ok) return;
      this._data.height_cm = h; this._data.weight_kg = w;
      this._showStep3();
    };
  },

  _showStep3() {
    this._updateBars(3);
    const t = k => I18n.t(k);
    document.getElementById('bmr-step-content').innerHTML = `
      <div class="step-label">${t('bmr.step3')}</div>
      <h2 class="bmr-title">${t('bmr.title')}</h2>
      <p class="bmr-subtitle">${t('bmr.subtitle')}</p>
      <div class="form-group">
        <label>${t('bmr.goal')}</label>
        <select id="bmr-goal" class="form-control">
          <option value="">--</option>
          <option value="improve_health">${t('bmr.goal_improve_health')}</option>
          <option value="body_recomp">${t('bmr.goal_body_recomp')}</option>
          <option value="fat_loss_slow">${t('bmr.goal_fat_loss_slow')}</option>
          <option value="fat_loss_moderate">${t('bmr.goal_fat_loss_moderate')}</option>
          <option value="fat_loss_fast">${t('bmr.goal_fat_loss_fast')}</option>
          <option value="muscle_gain_slow">${t('bmr.goal_muscle_gain_slow')}</option>
          <option value="muscle_gain_moderate">${t('bmr.goal_muscle_gain_moderate')}</option>
          <option value="muscle_gain_fast">${t('bmr.goal_muscle_gain_fast')}</option>
        </select>
        <div class="form-error" id="err-goal"></div>
      </div>
      <p class="bmr-hint" style="font-size:0.78rem;color:var(--text-3);margin-top:4px">${t('bmr.activity_moved_hint')}</p>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:24px">
        <button class="btn btn-ghost" id="s3-back">${t('bmr.back')}</button>
        <button class="btn btn-primary" id="s3-submit">${t('bmr.submit')}</button>
      </div>`;
    document.getElementById('s3-back').onclick = () => this._showStep2();
    document.getElementById('s3-submit').onclick = () => this._submit();
  },

  async _submit() {
    const goal = document.getElementById('bmr-goal').value;
    let ok = true;
    document.getElementById('err-goal').textContent = '';
    if (!goal) { document.getElementById('err-goal').textContent = I18n.lang === 'zh' ? '请选择目标' : 'Select a goal'; ok = false; }
    if (!ok) return;
    this._data.goal = goal;
    const btn = document.getElementById('s3-submit');
    btn.disabled = true;
    btn.textContent = I18n.t('common.loading');
    try {
      const result = await API.saveBMR(this._data);
      localStorage.setItem('ch_has_bmr', '1');
      this._showResult(result.bmr_value, result.tdee_value, result.calorie_target);
    } catch (err) {
      App.showToast(err.message || I18n.t('common.error'), 'error');
      btn.disabled = false;
      btn.textContent = I18n.t('bmr.submit');
    }
  },

  _showResult(bmr, tdee, calorieTarget) {
    const t = k => I18n.t(k);
    document.getElementById('bmr-step-content').innerHTML = `
      <h2 class="bmr-title" style="text-align:center">🎉</h2>
      <div class="bmr-result">
        <div class="metric">
          <div class="metric-label">${t('bmr.result_bmr')}</div>
          <div class="metric-value">${Math.round(bmr)}</div>
          <div class="metric-unit">kcal / day</div>
        </div>
        <div style="height:1px;background:var(--accent);opacity:0.3;margin:12px 0"></div>
        <div class="metric">
          <div class="metric-label">${t('bmr.result_tdee')}</div>
          <div class="metric-value">${tdee ? Math.round(tdee) : '—'}</div>
          <div class="metric-unit">kcal / day</div>
        </div>
        ${calorieTarget ? `
          <div style="height:1px;background:var(--accent);opacity:0.3;margin:12px 0"></div>
          <div class="metric">
            <div class="metric-label">${t('bmr.result_target')}</div>
            <div class="metric-value">${Math.round(calorieTarget)}</div>
            <div class="metric-unit">kcal / day</div>
          </div>` : ''}
      </div>
      <p style="text-align:center;margin-top:20px;font-size:0.84rem;color:var(--text-3)">
        ${I18n.lang === 'zh' ? '3秒后进入下一步：饮食偏好...' : 'Next: food preferences in 3 seconds...'}
      </p>`;
    setTimeout(() => App.showView('preferences'), 3000);
  }
};
