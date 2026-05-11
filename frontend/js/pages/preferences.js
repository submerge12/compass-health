/* ============================================================
   Compass Health — pages/preferences.js
   Food-preferences onboarding step (skippable)
   ============================================================ */

const PreferencesPage = {
  _known: null,
  _selected: {},

  async render() {
    const container = document.getElementById('preferences-container');
    if (!container) return;

    container.innerHTML = `<div class="bmr-card"><div class="loading-state"><span class="spinner"></span> ${I18n.t('common.loading')}</div></div>`;

    try {
      const res = await API.getFoodPreferences();
      this._known = res.known || {};
      this._selected = {};
      for (const [cat, items] of Object.entries(res.categories || {})) {
        const allowed = new Set(this._known[cat] || []);
        this._selected[cat] = new Set((items || []).filter(item => !allowed.size || allowed.has(item)));
      }
      for (const cat of Object.keys(this._known)) {
        if (!this._selected[cat]) this._selected[cat] = new Set();
      }
    } catch (err) {
      container.innerHTML = `<div class="bmr-card"><div class="empty-state">${this._esc(I18n.t('common.error'))}: ${this._esc(err.message)}</div><div style="display:flex;justify-content:flex-end;margin-top:16px"><button class="btn btn-ghost" id="prefs-skip-err">${this._esc(I18n.t('prefs.skip'))}</button></div></div>`;
      document.getElementById('prefs-skip-err')?.addEventListener('click', () => App.showView('main'));
      return;
    }

    this._paint(container);
  },

  _paint(container) {
    const lang = I18n.lang;
    const catOrder = ['grains','vegetables','fruits','meat_low_fat','meat_mid_fat','soy','dairy','nuts'];
    const cats = catOrder.filter(c => this._known[c]);

    const catsHtml = cats.map(cat => {
      const items = this._known[cat] || [];
      const chipsHtml = items.map(key => {
        const isOn = this._selected[cat]?.has(key) ? 'selected' : '';
        const label = PREF_LABELS[key]?.[lang] || key;
        return `<button type="button" class="pref-chip ${isOn}" data-cat="${cat}" data-key="${key}">${this._esc(label)}</button>`;
      }).join('');
      return `
        <div class="pref-category">
          <div class="pref-category-title">${this._esc(PREF_CATEGORY_LABELS[cat]?.[lang] || cat)}</div>
          <div class="pref-chips">${chipsHtml}</div>
        </div>`;
    }).join('');

    container.innerHTML = `
      <div class="bmr-card">
        <div class="step-label">${I18n.t('prefs.step_label')}</div>
        <h2 class="bmr-title">${I18n.t('prefs.title')}</h2>
        <p class="bmr-subtitle">${I18n.t('prefs.subtitle')}</p>
        <div class="pref-list">${catsHtml}</div>
        <div class="form-error" id="prefs-err" style="margin-top:12px"></div>
        <div style="display:flex;gap:10px;justify-content:space-between;margin-top:24px">
          <button class="btn btn-ghost" id="prefs-skip">${I18n.t('prefs.skip')}</button>
          <button class="btn btn-primary" id="prefs-save">${I18n.t('prefs.save')}</button>
        </div>
      </div>`;

    container.querySelectorAll('.pref-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const cat = btn.getAttribute('data-cat');
        const key = btn.getAttribute('data-key');
        const set = this._selected[cat];
        if (set.has(key)) { set.delete(key); btn.classList.remove('selected'); }
        else               { set.add(key);    btn.classList.add('selected'); }
      });
    });

    document.getElementById('prefs-skip').onclick = () => App.showView('main');
    document.getElementById('prefs-save').onclick = () => this._save();
  },

  async _save() {
    const items = [];
    for (const [cat, set] of Object.entries(this._selected)) {
      for (const key of set) items.push({ category: cat, item_key: key });
    }
    const btn = document.getElementById('prefs-save');
    const errEl = document.getElementById('prefs-err');
    if (errEl) errEl.textContent = '';
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('common.loading'); }
    try {
      await API.saveFoodPreferences(items, { replace: true });
      App.showView('main');
    } catch (err) {
      if (errEl) errEl.textContent = err.message || I18n.t('common.error');
      if (btn) { btn.disabled = false; btn.textContent = I18n.t('prefs.save'); }
    }
  },

  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
};

const PREF_CATEGORY_LABELS = {
  grains:       { zh: '谷物',     en: 'Grains' },
  vegetables:   { zh: '蔬菜',     en: 'Vegetables' },
  fruits:       { zh: '水果',     en: 'Fruits' },
  meat_low_fat: { zh: '低脂肉类', en: 'Lean Meat' },
  meat_mid_fat: { zh: '中脂肉类', en: 'Medium-fat Meat' },
  soy:          { zh: '豆制品',   en: 'Soy' },
  dairy:        { zh: '乳制品',   en: 'Dairy' },
  nuts:         { zh: '坚果',     en: 'Nuts' },
};

const PREF_LABELS = {
  // grains
  rice:                    { zh: '大米',       en: 'Rice' },
  brown_rice:              { zh: '糙米',       en: 'Brown Rice' },
  oats:                    { zh: '燕麦',       en: 'Oats' },
  buckwheat:               { zh: '荞麦',       en: 'Buckwheat' },
  quinoa:                  { zh: '藜麦',       en: 'Quinoa' },
  steamed_bun:             { zh: '馒头',       en: 'Steamed Bun' },
  sweet_potato:            { zh: '红薯',       en: 'Sweet Potato' },
  corn:                    { zh: '玉米',       en: 'Corn' },
  potato:                  { zh: '土豆',       en: 'Potato' },
  pumpkin:                 { zh: '南瓜',       en: 'Pumpkin' },
  // vegetables
  tomato:                  { zh: '番茄',       en: 'Tomato' },
  cucumber:                { zh: '黄瓜',       en: 'Cucumber' },
  broccoli:                { zh: '西兰花',     en: 'Broccoli' },
  cauliflower:             { zh: '菜花',       en: 'Cauliflower' },
  cabbage:                 { zh: '卷心菜',     en: 'Cabbage' },
  spinach:                 { zh: '菠菜',       en: 'Spinach' },
  bok_choy:                { zh: '小白菜',     en: 'Bok Choy' },
  kale:                    { zh: '羽衣甘蓝',   en: 'Kale' },
  amaranth:                { zh: '苋菜',       en: 'Amaranth' },
  mustard_greens:          { zh: '芥菜',       en: 'Mustard Greens' },
  carrot:                  { zh: '胡萝卜',     en: 'Carrot' },
  shiitake:                { zh: '香菇',       en: 'Shiitake' },
  shiitake_sun:            { zh: '晒干香菇',   en: 'Sun-dried Shiitake' },
  enoki:                   { zh: '金针菇',     en: 'Enoki' },
  wood_ear:                { zh: '木耳',       en: 'Wood Ear' },
  kelp:                    { zh: '海带',       en: 'Kelp' },
  seaweed:                 { zh: '紫菜',       en: 'Seaweed' },
  // fruits
  blueberry:               { zh: '蓝莓',       en: 'Blueberry' },
  strawberry:              { zh: '草莓',       en: 'Strawberry' },
  cherry_tomato:           { zh: '圣女果',     en: 'Cherry Tomato' },
  pomelo:                  { zh: '柚子',       en: 'Pomelo' },
  pineapple:               { zh: '菠萝',       en: 'Pineapple' },
  mulberry:                { zh: '桑葚',       en: 'Mulberry' },
  apple:                   { zh: '苹果',       en: 'Apple' },
  raspberry:               { zh: '树莓',       en: 'Raspberry' },
  banana:                  { zh: '香蕉',       en: 'Banana' },
  orange:                  { zh: '橙子',       en: 'Orange' },
  kiwi:                    { zh: '猕猴桃',     en: 'Kiwi' },
  // lean meat
  chicken_breast:          { zh: '鸡胸肉',     en: 'Chicken Breast' },
  chicken_thigh_skinless:  { zh: '去皮鸡腿',   en: 'Chicken Thigh (skinless)' },
  duck_breast:             { zh: '鸭胸肉',     en: 'Duck Breast' },
  pork_tenderloin:         { zh: '猪里脊',     en: 'Pork Tenderloin' },
  fish:                    { zh: '鱼',         en: 'Fish' },
  cod:                     { zh: '鳕鱼',       en: 'Cod' },
  sea_bass:                { zh: '鲈鱼',       en: 'Sea Bass' },
  tilapia:                 { zh: '罗非鱼',     en: 'Tilapia' },
  shrimp:                  { zh: '虾',         en: 'Shrimp' },
  egg_white:               { zh: '蛋清',       en: 'Egg White' },
  // mid-fat meat
  whole_egg:               { zh: '整蛋',       en: 'Whole Egg' },
  egg_yolk:                { zh: '蛋黄',       en: 'Egg Yolk' },
  beef_tenderloin:         { zh: '牛里脊',     en: 'Beef Tenderloin' },
  beef_sirloin:            { zh: '牛外脊',     en: 'Beef Sirloin' },
  lamb:                    { zh: '羊肉',       en: 'Lamb' },
  beef_liver:              { zh: '牛肝',       en: 'Beef Liver' },
  chicken_liver:           { zh: '鸡肝',       en: 'Chicken Liver' },
  duck_blood:              { zh: '鸭血',       en: 'Duck Blood' },
  salmon:                  { zh: '三文鱼',     en: 'Salmon' },
  hairtail:                { zh: '带鱼',       en: 'Hairtail' },
  mackerel:                { zh: '鲭鱼',       en: 'Mackerel' },
  sardine:                 { zh: '沙丁鱼',     en: 'Sardine' },
  oyster:                  { zh: '牡蛎',       en: 'Oyster' },
  clam:                    { zh: '蛤蜊',       en: 'Clam' },
  mussel:                  { zh: '青口',       en: 'Mussel' },
  scallop:                 { zh: '扇贝',       en: 'Scallop' },
  // soy
  tofu_firm:               { zh: '老豆腐',     en: 'Firm Tofu' },
  tofu_soft:               { zh: '嫩豆腐',     en: 'Soft Tofu' },
  dried_tofu:              { zh: '豆腐干',     en: 'Dried Tofu' },
  soy_milk:                { zh: '豆浆',       en: 'Soy Milk' },
  natto:                   { zh: '纳豆',       en: 'Natto' },
  tempeh:                  { zh: '天贝',       en: 'Tempeh' },
  edamame:                 { zh: '毛豆',       en: 'Edamame' },
  // dairy
  milk:                    { zh: '牛奶',       en: 'Milk' },
  yogurt:                  { zh: '酸奶',       en: 'Yogurt' },
  greek_yogurt:            { zh: '希腊酸奶',   en: 'Greek Yogurt' },
  cheese:                  { zh: '奶酪',       en: 'Cheese' },
  // nuts & seeds
  nuts:                    { zh: '坚果',       en: 'Nuts' },
  nut_mix:                 { zh: '坚果堆',     en: 'Mixed Nuts' },
  walnuts:                 { zh: '核桃',       en: 'Walnuts' },
  almonds:                 { zh: '杏仁',       en: 'Almonds' },
  cashews:                 { zh: '腰果',       en: 'Cashews' },
  pumpkin_seeds:           { zh: '南瓜籽',     en: 'Pumpkin Seeds' },
  sunflower_seeds:         { zh: '葵花籽',     en: 'Sunflower Seeds' },
  brazil_nuts:             { zh: '巴西坚果',   en: 'Brazil Nuts' },
  flaxseed:                { zh: '亚麻籽',     en: 'Flaxseed' },
  chia_seed:               { zh: '奇亚籽',     en: 'Chia Seeds' },
  sesame:                  { zh: '芝麻',       en: 'Sesame' },
  olive_oil:               { zh: '橄榄油',     en: 'Olive Oil' },
  cooking_oil:             { zh: '其他炒菜油', en: 'Other Cooking Oil' },
};
