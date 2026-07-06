/* ============================================================
   Compass Health — pages/stats.js
   Health Statistics page with SVG charts
   ============================================================ */

const StatsPage = {
  _currentWeight: null,
  _tdee: null,
  _dietAvg: null,

  async render() {
    const el = document.getElementById('page-stats');
    if (!el) return;
    const t = k => I18n.t(k);

    el.innerHTML = `
      <div class="page-header">
        <div><h2>${t('stats.title')}</h2></div>
      </div>
      <div id="stats-content">
        <div style="color:var(--text-3);text-align:center;padding:40px">${t('common.loading')}</div>
      </div>`;

    try {
      const [summary, weekly, user] = await Promise.all([
        API.getStatsSummary(), API.getStatsWeekly(), API.getMe()
      ]);
      this._renderContent(summary, weekly, user, t);
    } catch (err) {
      document.getElementById('stats-content').innerHTML =
        `<div style="color:var(--rust);text-align:center;padding:40px">${this._esc(err.message)}</div>`;
    }
  },

  _renderContent(summary, weekly, user, t) {
    const el = document.getElementById('stats-content');
    const weightData = summary.weight_trend || [];
    const isZh = I18n.lang === 'zh';

    // Store values needed for weight prediction
    const lastWeight = weightData.length ? weightData[weightData.length - 1].weight_kg : null;
    this._currentWeight = lastWeight;
    this._tdee = user?.tdee || null;
    this._dietAvg = summary.diet_7d_avg_calories || 0;

    el.innerHTML = `
      <!-- Summary Cards -->
      <div class="grid-3" style="margin-bottom:24px">
        <div class="card">
          <div class="card-title">💧 ${t('stats.water_avg')}</div>
          <div class="card-value">${summary.water_7d_avg_ml}</div>
          <div class="card-sub">ml / day</div>
        </div>
        <div class="card">
          <div class="card-title">🏃 ${t('stats.exercise_avg')}</div>
          <div class="card-value">${summary.exercise_7d_avg_calories}</div>
          <div class="card-sub">kcal / day</div>
        </div>
        <div class="card">
          <div class="card-title">🥗 ${t('stats.diet_avg')}</div>
          <div class="card-value">${summary.diet_7d_avg_calories}</div>
          <div class="card-sub">kcal / day</div>
        </div>
      </div>

      <!-- Check-in streak -->
      <div class="card" style="margin-bottom:24px">
        <div class="card-title">✅ ${t('stats.checkin_streak')}</div>
        <div class="card-value">${summary.checkin_streak} <span style="font-size:1rem;color:var(--text-3)">${t('dash.days')}</span></div>
      </div>

      <!-- Weight trend (SVG line chart) -->
      <div class="card" style="margin-bottom:24px">
        <div class="card-title">⚖️ ${t('stats.weight_trend')}</div>
        <div id="weight-chart"></div>
      </div>

      <!-- Weight goal predictor -->
      <div class="card" style="margin-bottom:24px">
        <div class="card-title">🎯 ${isZh ? '目标体重预测' : 'Weight Goal Predictor'}</div>
        <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px">
          <div style="flex:1;min-width:160px">
            <label style="font-size:0.78rem;color:var(--text-3);display:block;margin-bottom:4px">
              ${isZh ? '目标体重 (kg)' : 'Target Weight (kg)'}
            </label>
            <input type="number" id="target-weight-input" class="form-control"
                   step="0.1" min="30" max="300"
                   placeholder="${isZh ? '例：60' : 'e.g. 60'}">
          </div>
          <button class="btn btn-sm" style="background:var(--accent);color:#fff;white-space:nowrap"
                  onclick="StatsPage._calcWeightGoal()">
            ${isZh ? '计算预测' : 'Calculate'}
          </button>
        </div>
        <div id="weight-prediction-result"></div>
      </div>

      <!-- 7-day water bar chart -->
      <div class="card" style="margin-bottom:24px">
        <div class="card-title">💧 ${t('stats.water_trend')}</div>
        <div class="bar-chart" id="stats-water-chart"></div>
      </div>

      <!-- 7-day exercise bar chart -->
      <div class="card" style="margin-bottom:24px">
        <div class="card-title">🏃 ${t('stats.exercise_trend')}</div>
        <div class="bar-chart" id="stats-exercise-chart"></div>
      </div>

      <!-- 7-day diet bar chart -->
      <div class="card">
        <div class="card-title">🥗 ${t('stats.diet_trend')}</div>
        <div class="bar-chart" id="stats-diet-chart"></div>
      </div>`;

    // Weight SVG line chart
    this._renderWeightChart(weightData);

    // 7-day water bars
    this._renderWaterBars(weekly);

    // 7-day exercise bars
    this._renderExerciseBars(weekly);

    // 7-day diet bars
    this._renderDietBars(weekly);
  },

  _renderWeightChart(data) {
    const container = document.getElementById('weight-chart');
    if (!container) return;
    if (!data || !data.length) {
      container.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem;text-align:center;padding:20px">${I18n.t('common.no_data')}</div>`;
      return;
    }

    const W = 600, H = 120, pad = 30;
    const weights = data.map(d => d.weight_kg);
    const minW = Math.min(...weights) - 1;
    const maxW = Math.max(...weights) + 1;
    const n = data.length;

    const xScale = i => pad + (i / (n - 1 || 1)) * (W - pad * 2);
    const yScale = v => H - pad - ((v - minW) / (maxW - minW || 1)) * (H - pad * 2);

    const points = data.map((d, i) => `${xScale(i)},${yScale(d.weight_kg)}`).join(' ');
    const circles = data.map((d, i) =>
      `<circle cx="${xScale(i)}" cy="${yScale(d.weight_kg)}" r="4" fill="var(--accent)">
         <title>${d.date}: ${d.weight_kg} kg</title>
       </circle>`
    ).join('');

    // Y-axis labels
    const yLabels = [minW + 1, (minW + maxW) / 2, maxW - 1].map(v => ({
      y: yScale(v), label: v.toFixed(1)
    }));

    container.innerHTML = `
      <div class="line-chart-wrap">
        <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
          ${yLabels.map(({ y, label }) => `
            <line x1="${pad}" y1="${y}" x2="${W - pad}" y2="${y}" stroke="var(--border)" stroke-width="1"/>
            <text x="${pad - 4}" y="${y + 4}" text-anchor="end" font-size="9" fill="var(--text-3)">${label}</text>
          `).join('')}
          <polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>
          ${circles}
          ${data.map((d, i) => `<text x="${xScale(i)}" y="${H - 4}" text-anchor="middle" font-size="8" fill="var(--text-3)">${d.date.slice(5)}</text>`).join('')}
        </svg>
      </div>`;
  },

  _renderWaterBars(weekly) {
    const container = document.getElementById('stats-water-chart');
    if (!container || !weekly) return;
    const max = Math.max(...weekly.map(d => d.water_ml), 1);
    const todayStr = this._todayDateString();
    container.innerHTML = weekly.map(d => {
      const h = Math.round((d.water_ml / max) * 80);
      return `
        <div class="bar-col ${d.date === todayStr ? 'today' : ''}">
          <div class="bar" style="height:${h}px" title="${d.water_ml} ml"></div>
          <div class="bar-label">${d.date.slice(5)}</div>
        </div>`;
    }).join('');
  },

  _renderExerciseBars(weekly) {
    const container = document.getElementById('stats-exercise-chart');
    if (!container || !weekly) return;
    const max = Math.max(...weekly.map(d => d.exercise_calories), 1);
    const todayStr = this._todayDateString();
    container.innerHTML = weekly.map(d => {
      const h = Math.round((d.exercise_calories / max) * 80);
      return `
        <div class="bar-col ${d.date === todayStr ? 'today' : ''}">
          <div class="bar" style="height:${h}px" title="${d.exercise_calories} kcal"></div>
          <div class="bar-label">${d.date.slice(5)}</div>
        </div>`;
    }).join('');
  },

  _renderDietBars(weekly) {
    const container = document.getElementById('stats-diet-chart');
    if (!container || !weekly) return;
    const max = Math.max(...weekly.map(d => d.diet_calories), 1);
    const todayStr = this._todayDateString();
    container.innerHTML = weekly.map(d => {
      const h = Math.round((d.diet_calories / max) * 80);
      return `
        <div class="bar-col ${d.date === todayStr ? 'today' : ''}">
          <div class="bar" style="height:${h}px" title="${d.diet_calories} kcal"></div>
          <div class="bar-label">${d.date.slice(5)}</div>
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

  _calcWeightGoal() {
    const isZh = I18n.lang === 'zh';
    const resultEl = document.getElementById('weight-prediction-result');
    if (!resultEl) return;

    const targetWeight = parseFloat(document.getElementById('target-weight-input')?.value);

    if (!targetWeight || targetWeight < 30 || targetWeight > 300) {
      resultEl.innerHTML = `<div style="color:var(--rust);font-size:0.84rem">
        ${isZh ? '请输入有效目标体重 (30–300 kg)' : 'Enter a valid target weight (30–300 kg)'}
      </div>`;
      return;
    }

    if (!this._currentWeight) {
      resultEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">
        ${isZh ? '请先在体征页面记录体重' : 'Please log your weight in the Condition page first'}
      </div>`;
      return;
    }

    if (!this._tdee) {
      resultEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">
        ${isZh ? '请先完成 BMR 设置' : 'Please complete BMR setup first'}
      </div>`;
      return;
    }

    const weightDiff = this._currentWeight - targetWeight;
    if (weightDiff <= 0) {
      resultEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">
        ${isZh ? '目标体重须低于当前体重' : 'Target weight must be below your current weight'}
      </div>`;
      return;
    }

    // 3,000 kcal deficit = 1 kg loss
    const dailyDeficit = this._tdee - this._dietAvg;
    if (dailyDeficit <= 0) {
      resultEl.innerHTML = `<div style="color:var(--text-3);font-size:0.84rem">
        ${isZh
          ? `当前 7 日平均摄入 (${Math.round(this._dietAvg)} kcal) 未低于 TDEE (${Math.round(this._tdee)} kcal)，暂无减重预测`
          : `7-day avg intake (${Math.round(this._dietAvg)} kcal) is not below TDEE (${Math.round(this._tdee)} kcal) — no weight loss projected`}
      </div>`;
      return;
    }

    const daysToGoal = Math.round((weightDiff * 3000) / dailyDeficit);
    const goalDate = new Date();
    goalDate.setDate(goalDate.getDate() + daysToGoal);
    const goalDateStr = goalDate.toLocaleDateString(isZh ? 'zh-CN' : 'en-US', {
      year: 'numeric', month: 'long', day: 'numeric'
    });

    resultEl.innerHTML = `
      <div style="background:var(--surface-2);border-radius:var(--radius);padding:12px 14px">
        <div style="display:flex;gap:20px;flex-wrap:wrap">
          <div>
            <div style="font-size:0.72rem;color:var(--text-3)">${isZh ? '当前体重' : 'Current'}</div>
            <div style="font-size:1.05rem;font-weight:600">${this._currentWeight} kg</div>
          </div>
          <div>
            <div style="font-size:0.72rem;color:var(--text-3)">${isZh ? '每日赤字' : 'Daily Deficit'}</div>
            <div style="font-size:1.05rem;font-weight:600">${Math.round(dailyDeficit)} kcal</div>
          </div>
          <div>
            <div style="font-size:0.72rem;color:var(--text-3)">${isZh ? '预计天数' : 'Est. Days'}</div>
            <div style="font-size:1.05rem;font-weight:600;color:var(--accent)">${daysToGoal} ${isZh ? '天' : 'days'}</div>
          </div>
          <div>
            <div style="font-size:0.72rem;color:var(--text-3)">${isZh ? '预计达成日期' : 'Est. Date'}</div>
            <div style="font-size:1.05rem;font-weight:600;color:var(--accent)">${goalDateStr}</div>
          </div>
        </div>
      </div>`;
  },

  _esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }
};
