/* ============================================================
   Compass Health — pages/community_recipes.js
   Community low-fat recipe forum
   ============================================================ */

const CommunityRecipesPage = {
  _recipes: null,

  async render() {
    const el = document.getElementById('page-community');
    if (!el) return;
    const isZh = I18n.lang === 'zh';
    el.innerHTML = `
      <div class="diet-page-head community-page-head">
        <div>
          <div class="diet-kicker">${isZh ? '用户菜谱 · AI 低脂评分 · 试做反馈' : 'User recipes · AI score · Trial feedback'}</div>
          <h2>${isZh ? '低脂菜谱社区' : 'Low-fat Recipe Community'}</h2>
        </div>
        <button class="btn btn-primary btn-sm" id="community-recipe-btn" type="button">
          ${isZh ? '提交菜谱' : 'Submit Recipe'}
        </button>
      </div>

      <section class="community-page-toolbar">
        <div>
          <strong>${isZh ? '真实做过，才有意义' : 'Useful because people actually try it'}</strong>
          <span>${isZh ? '先看 AI 低脂评分，再看用户试做后的满意度、饱腹感和难度。' : 'Start with the AI low-fat score, then compare satisfaction, satiety, and difficulty from real trials.'}</span>
        </div>
        <button class="btn btn-ghost btn-sm" id="community-refresh-btn" type="button">
          ${isZh ? '刷新' : 'Refresh'}
        </button>
      </section>

      <section id="community-recipe-list" class="community-page-list">
        <div style="color:var(--text-3);padding:12px 0">${I18n.t('common.loading')}</div>
      </section>`;

    document.getElementById('community-recipe-btn').onclick = () => this._showSubmitModal();
    document.getElementById('community-refresh-btn').onclick = () => this._loadRecipes({ force: true });
    await this._loadRecipes();
  },

  async _loadRecipes({ force = false } = {}) {
    const container = document.getElementById('community-recipe-list');
    if (!container) return;
    if (force || this._recipes === null) {
      container.innerHTML = `<div style="color:var(--text-3);padding:12px 0">${I18n.t('common.loading')}</div>`;
      try {
        this._recipes = await API.getCommunityRecipes();
      } catch (err) {
        this._recipes = [];
        container.innerHTML = `<div style="color:var(--rust);padding:12px 0">${this._esc(err.message)}</div>`;
        return;
      }
    }
    this._renderRecipes();
  },

  _renderRecipes() {
    const container = document.getElementById('community-recipe-list');
    if (!container) return;
    const items = this._recipes || [];
    const isZh = I18n.lang === 'zh';
    if (!items.length) {
      container.innerHTML = `
        <div class="recipe-community-empty">
          ${isZh ? '还没有社区菜谱。先发一道你常做、能说清克数和做法的菜。' : 'No community recipes yet. Share a dish with clear portions and method.'}
        </div>`;
      return;
    }
    container.innerHTML = `
      <div class="community-recipe-grid">
        ${items.map(r => this._card(r, isZh)).join('')}
      </div>`;
  },

  _card(r, isZh) {
    const assessment = r.low_fat_assessment || {};
    const nutrition = assessment.estimated_nutrition_per_serving || {};
    const rating = r.community_rating_count
      ? `${Number(r.community_rating_avg || 0).toFixed(1)} / 5 · ${r.community_rating_count}`
      : (isZh ? '等待试做评分' : 'No trial ratings yet');
    return `
      <article class="community-recipe-card">
        <div class="community-recipe-top">
          <div>
            <div class="recipe-card-title">${this._esc(r.name)}</div>
            <div class="community-recipe-meta">${isZh ? '社区菜谱' : 'Community recipe'}</div>
          </div>
          <span class="low-fat-score ${this._scoreClass(r.low_fat_score)}">${Number(r.low_fat_score || 0)}</span>
        </div>
        <div class="community-recipe-summary">${this._esc(assessment.summary_zh || '')}</div>
        <div class="community-macro-row">
          <span>${Math.round(Number(nutrition.kcal || 0)) || '--'} kcal</span>
          <span>P ${this._formatMacro(nutrition.protein_g)}g</span>
          <span>F ${this._formatMacro(nutrition.fat_g)}g</span>
        </div>
        <div class="community-rating-row">
          <span>${this._esc(rating)}</span>
          ${r.my_trial_rating ? `<span>${isZh ? '我已评分' : 'My rating saved'}</span>` : ''}
        </div>
        <div class="community-actions">
          <button class="btn btn-ghost btn-sm" onclick="CommunityRecipesPage._showRecipeModal(${r.id})">${isZh ? '查看菜谱' : 'View'}</button>
          <button class="btn btn-sm btn-primary" onclick="CommunityRecipesPage._showTrialRatingModal(${r.id})">${isZh ? '试做后评分' : 'Rate after trying'}</button>
        </div>
      </article>`;
  },

  _showSubmitModal() {
    const isZh = I18n.lang === 'zh';
    App.openModal(
      isZh ? '提交低脂菜谱' : 'Submit Low-fat Recipe',
      `<div class="community-submit-form">
         <div class="form-group">
           <label>${isZh ? '菜名 *' : 'Recipe name *'}</label>
           <input id="community-name" class="form-control" placeholder="${isZh ? '例：少油青椒鸡胸肉' : 'e.g. Low-oil pepper chicken breast'}">
         </div>
         <div class="form-group">
           <label>${isZh ? '几人份' : 'Servings'}</label>
           <input id="community-servings" class="form-control" type="number" min="1" max="20" value="1">
         </div>
         <div class="form-group">
           <label>${isZh ? '食材和克数 *' : 'Ingredients and grams *'}</label>
           <textarea id="community-ingredients" class="form-textarea" rows="5"
             placeholder="${isZh ? '鸡胸肉 160g\n西兰花 220g\n食用油 6g' : 'chicken breast 160g\nbroccoli 220g\noil 6g'}"></textarea>
         </div>
         <div class="form-group">
           <label>${isZh ? '制作流程 *' : 'Cooking method *'}</label>
           <textarea id="community-steps" class="form-textarea" rows="5"
             placeholder="${isZh ? '1. 西兰花焯水\n2. 鸡胸肉少油快炒' : '1. Blanch broccoli\n2. Stir-fry chicken with little oil'}"></textarea>
         </div>
         <div class="form-group">
           <label>${isZh ? '视频链接（可选）' : 'Video URL (optional)'}</label>
           <input id="community-video" class="form-control" placeholder="https://...">
         </div>
         <div id="community-assessment-preview"></div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-ghost" id="community-analyze-btn" onclick="CommunityRecipesPage._analyzeRecipe()">${isZh ? 'AI 评分' : 'AI Score'}</button>
       <button class="btn btn-primary" id="community-publish-btn" onclick="CommunityRecipesPage._publishRecipe()">${isZh ? '评分并发布' : 'Score and publish'}</button>`
    );
  },

  _payloadFromForm() {
    return {
      name: document.getElementById('community-name')?.value.trim() || '',
      servings: Number(document.getElementById('community-servings')?.value || 1),
      ingredients: document.getElementById('community-ingredients')?.value.trim() || '',
      steps: document.getElementById('community-steps')?.value.trim() || '',
      video_url: document.getElementById('community-video')?.value.trim() || null,
      category: 'community_low_fat',
    };
  },

  _validatePayload(payload) {
    const isZh = I18n.lang === 'zh';
    if (!payload.name || !payload.ingredients || !payload.steps) {
      App.showToast(isZh ? '请填写菜名、食材和制作流程' : 'Fill in name, ingredients, and method', 'error');
      return false;
    }
    if (!Number.isFinite(payload.servings) || payload.servings < 1 || payload.servings > 20) {
      App.showToast(isZh ? '份数需要在 1-20 之间' : 'Servings must be 1-20', 'error');
      return false;
    }
    return true;
  },

  async _analyzeRecipe() {
    const payload = this._payloadFromForm();
    if (!this._validatePayload(payload)) return;
    const btn = document.getElementById('community-analyze-btn');
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      const assessment = await API.analyzeCommunityRecipe(payload);
      const box = document.getElementById('community-assessment-preview');
      if (box) box.innerHTML = this._assessmentHtml(assessment);
    } catch (err) {
      App.showToast(err.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = I18n.lang === 'zh' ? 'AI 评分' : 'AI Score';
      }
    }
  },

  async _publishRecipe() {
    const payload = this._payloadFromForm();
    if (!this._validatePayload(payload)) return;
    const btn = document.getElementById('community-publish-btn');
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      const recipe = await API.createCommunityRecipe(payload);
      App.closeModal();
      this._recipes = null;
      await this._loadRecipes({ force: true });
      App.showToast(I18n.lang === 'zh' ? `已发布，低脂评分 ${recipe.low_fat_score}/100` : `Published with score ${recipe.low_fat_score}/100`, 'success');
    } catch (err) {
      App.showToast(err.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = I18n.lang === 'zh' ? '评分并发布' : 'Score and publish';
      }
    }
  },

  _showRecipeModal(recipeId) {
    const r = (this._recipes || []).find(x => x.id === recipeId);
    if (!r) return;
    const isZh = I18n.lang === 'zh';
    const ingHtml = (r.ingredients || '').split('\n').map(l => `<div>${this._esc(l)}</div>`).join('');
    const stepsHtml = (r.steps || '').split('\n').map(l => `<div>${this._esc(l)}</div>`).join('');
    App.openModal(
      this._esc(r.name),
      `<div class="community-detail">
         ${this._assessmentHtml(r.low_fat_assessment || {})}
         <div class="community-detail-section">
           <h4>${isZh ? '食材' : 'Ingredients'}</h4>
           <div>${ingHtml}</div>
         </div>
         <div class="community-detail-section">
           <h4>${isZh ? '做法' : 'Method'}</h4>
           <div>${stepsHtml}</div>
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="CommunityRecipesPage._showTrialRatingModal(${r.id})">${isZh ? '试做后评分' : 'Rate after trying'}</button>`
    );
  },

  _showTrialRatingModal(recipeId) {
    const r = (this._recipes || []).find(x => x.id === recipeId);
    if (!r) return;
    const isZh = I18n.lang === 'zh';
    const existing = r.my_trial_rating || {};
    App.openModal(
      isZh ? '试做评分' : 'Trial Rating',
      `<div class="community-submit-form">
         <div class="form-group">
           <label>${isZh ? '满意度评分' : 'Satisfaction rating'}</label>
           <select id="trial-rating" class="form-control">
             ${[5,4,3,2,1].map(v => `<option value="${v}" ${Number(existing.rating || 5) === v ? 'selected' : ''}>${v}</option>`).join('')}
           </select>
         </div>
         <div class="form-group">
           <label>${isZh ? '饱腹感' : 'Satiety'}</label>
           <select id="trial-satiety" class="form-control">
             <option value="">--</option>
             ${[5,4,3,2,1].map(v => `<option value="${v}" ${Number(existing.satiety_score || 0) === v ? 'selected' : ''}>${v}</option>`).join('')}
           </select>
         </div>
         <div class="form-group">
           <label>${isZh ? '制作难度' : 'Difficulty'}</label>
           <select id="trial-difficulty" class="form-control">
             <option value="">--</option>
             ${[1,2,3,4,5].map(v => `<option value="${v}" ${Number(existing.difficulty_score || 0) === v ? 'selected' : ''}>${v}</option>`).join('')}
           </select>
         </div>
         <label class="community-checkbox">
           <input id="trial-again" type="checkbox" ${existing.would_cook_again ? 'checked' : ''}>
           <span>${isZh ? '我愿意再做一次' : 'I would cook it again'}</span>
         </label>
         <div class="form-group">
           <label>${isZh ? '反馈' : 'Feedback'}</label>
           <textarea id="trial-feedback" class="form-textarea" rows="4" placeholder="${isZh ? '口味、饱腹感、哪里需要改...' : 'Taste, satiety, what to improve...'}">${this._esc(existing.feedback || '')}</textarea>
         </div>
       </div>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">${I18n.t('common.cancel')}</button>
       <button class="btn btn-primary" onclick="CommunityRecipesPage._submitTrialRating(${recipeId})">${I18n.t('common.save')}</button>`
    );
  },

  async _submitTrialRating(recipeId) {
    const body = {
      rating: Number(document.getElementById('trial-rating')?.value || 5),
      satiety_score: document.getElementById('trial-satiety')?.value ? Number(document.getElementById('trial-satiety').value) : null,
      difficulty_score: document.getElementById('trial-difficulty')?.value ? Number(document.getElementById('trial-difficulty').value) : null,
      would_cook_again: !!document.getElementById('trial-again')?.checked,
      feedback: document.getElementById('trial-feedback')?.value.trim() || null,
    };
    try {
      const updated = await API.rateCommunityRecipe(recipeId, body);
      this._recipes = (this._recipes || []).map(item => item.id === recipeId ? updated : item);
      this._renderRecipes();
      App.closeModal();
      App.showToast(I18n.lang === 'zh' ? '评分已保存' : 'Rating saved', 'success');
    } catch (err) {
      App.showToast(err.message, 'error');
    }
  },

  _assessmentHtml(assessment) {
    const isZh = I18n.lang === 'zh';
    const nutrition = assessment.estimated_nutrition_per_serving || {};
    const scores = assessment.dimension_scores || {};
    return `
      <div class="community-assessment ${this._scoreClass(assessment.score)}">
        <div class="community-assessment-head">
          <span>${isZh ? '低脂适配分' : 'Low-fat score'}</span>
          <strong>${Number(assessment.score || 0)} / 100</strong>
        </div>
        <p>${this._esc(assessment.summary_zh || '')}</p>
        <div class="community-macro-row">
          <span>${Math.round(Number(nutrition.kcal || 0)) || '--'} kcal</span>
          <span>P ${this._formatMacro(nutrition.protein_g)}g</span>
          <span>C ${this._formatMacro(nutrition.carbs_g)}g</span>
          <span>F ${this._formatMacro(nutrition.fat_g)}g</span>
        </div>
        <div class="community-score-grid">
          ${Object.entries(scores).map(([key, value]) => `
            <div><span>${this._dimensionLabel(key, isZh)}</span><strong>${Number(value || 0)}</strong></div>
          `).join('')}
        </div>
        <ul class="community-suggestion-list">
          ${(assessment.suggestions || []).map(s => `<li>${this._esc(s)}</li>`).join('')}
        </ul>
      </div>`;
  },

  _dimensionLabel(key, isZh) {
    const zh = {
      fat_control: '脂肪控制',
      calorie_density: '热量密度',
      protein_quality: '蛋白质量',
      fiber_and_vegetables: '蔬菜纤维',
      cooking_method: '烹饪方式',
      portion_clarity: '克数清晰度',
    };
    const en = {
      fat_control: 'Fat control',
      calorie_density: 'Calories',
      protein_quality: 'Protein',
      fiber_and_vegetables: 'Vegetables',
      cooking_method: 'Method',
      portion_clarity: 'Portions',
    };
    return (isZh ? zh : en)[key] || key;
  },

  _scoreClass(score) {
    const n = Number(score || 0);
    if (n >= 70) return 'good';
    if (n >= 55) return 'warn';
    return 'risk';
  },

  _formatMacro(value) {
    const number = Number(value || 0);
    const rounded = Math.round(number * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  },

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  },
};
