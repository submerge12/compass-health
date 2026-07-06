/* ============================================================
   Compass Health — pages/preferences.js
   Food-preferences onboarding step (skippable)
   ============================================================ */

const PreferencesPage = {
  _known: null,
  _nutrientGroups: {},
  _selected: {},
  _slugToCategory: {},
  _viewMode: 'category',

  async render() {
    const container = document.getElementById('preferences-container');
    if (!container) return;

    container.innerHTML = `<div class="bmr-card"><div class="loading-state"><span class="spinner"></span> ${I18n.t('common.loading')}</div></div>`;

    try {
      const res = await API.getFoodPreferences();
      this._known = res.known || {};
      this._nutrientGroups = res.nutrient_groups || {};
      this._slugToCategory = this._buildSlugToCategory();
      this._viewMode = 'category';
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
    const hasNutrientGroups = this._hasNutrientGroups();
    const mode = this._viewMode === 'nutrient' && hasNutrientGroups ? 'nutrient' : 'category';
    this._viewMode = mode;

    const groups = mode === 'nutrient' ? this._nutrientGroupsForRender(lang) : this._categoryGroupsForRender(lang);
    const modeHtml = hasNutrientGroups ? `
        <div class="pref-mode-switch" role="tablist" aria-label="${this._esc(I18n.t('prefs.view_mode'))}">
          <button type="button" class="pref-mode-btn ${mode === 'category' ? 'active' : ''}" data-pref-mode="category" role="tab" aria-selected="${mode === 'category'}">${this._esc(I18n.t('prefs.by_category'))}</button>
          <button type="button" class="pref-mode-btn ${mode === 'nutrient' ? 'active' : ''}" data-pref-mode="nutrient" role="tab" aria-selected="${mode === 'nutrient'}">${this._esc(I18n.t('prefs.by_nutrient'))}</button>
        </div>` : '';

    const catsHtml = groups.map(group => {
      const chipsHtml = group.items.map(key => {
        const cat = this._slugToCategory[key];
        if (!cat || !this._selected[cat]) return '';
        const isOn = this._selected[cat].has(key) ? 'selected' : '';
        const label = this._foodLabel(key, lang);
        return `<button type="button" class="pref-chip ${isOn}" data-cat="${this._esc(cat)}" data-key="${this._esc(key)}">${this._esc(label)}</button>`;
      }).join('');
      if (!chipsHtml) return '';
      return `
        <div class="pref-category">
          <div class="pref-category-title">${this._esc(group.label)}</div>
          <div class="pref-chips">${chipsHtml}</div>
        </div>`;
    }).join('');

    container.innerHTML = `
      <div class="bmr-card">
        <div class="step-label">${I18n.t('prefs.step_label')}</div>
        <h2 class="bmr-title">${I18n.t('prefs.title')}</h2>
        <p class="bmr-subtitle">${I18n.t('prefs.subtitle')}</p>
        ${modeHtml}
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
        if (!set) return;
        let selected = false;
        if (set.has(key)) { set.delete(key); }
        else               { set.add(key); selected = true; }
        container.querySelectorAll(`.pref-chip[data-key="${key}"]`).forEach(chip => {
          chip.classList.toggle('selected', selected);
        });
      });
    });

    container.querySelectorAll('[data-pref-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        const next = btn.getAttribute('data-pref-mode');
        if (next && next !== this._viewMode) {
          this._viewMode = next;
          this._paint(container);
        }
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

  _buildSlugToCategory() {
    const result = {};
    for (const [cat, items] of Object.entries(this._known || {})) {
      (items || []).forEach(key => {
        if (!result[key]) result[key] = cat;
      });
    }
    return result;
  },

  _categoryGroupsForRender(lang) {
    const ordered = PREF_CATEGORY_ORDER.filter(cat => this._known[cat]);
    const extras = Object.keys(this._known || {}).filter(cat => !PREF_CATEGORY_ORDER.includes(cat));
    return ordered.concat(extras).map(cat => ({
      key: cat,
      label: PREF_CATEGORY_LABELS[cat]?.[lang] || cat,
      items: this._known[cat] || [],
    }));
  },

  _nutrientGroupsForRender(lang) {
    const knownRoles = Object.keys(this._nutrientGroups || {});
    const ordered = PREF_NUTRIENT_ORDER.filter(role => knownRoles.includes(role));
    const extras = knownRoles.filter(role => !PREF_NUTRIENT_ORDER.includes(role));
    return ordered.concat(extras).map(role => ({
      key: role,
      label: PREF_NUTRIENT_LABELS[role]?.[lang] || role,
      items: (this._nutrientGroups[role] || []).filter(key => this._slugToCategory[key]),
    }));
  },

  _hasNutrientGroups() {
    return Object.values(this._nutrientGroups || {}).some(items =>
      Array.isArray(items) && items.some(key => this._slugToCategory[key])
    );
  },

  _foodLabel(key, lang) {
    return PREF_LABELS[key]?.[lang] || key;
  },

  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
};

const PREF_CATEGORY_ORDER = ['grains','vegetables','fruits','meat_low_fat','meat_mid_fat','soy','dairy','nuts'];

const PREF_NUTRIENT_ORDER = [
  'calcium',
  'iron',
  'zinc',
  'iodine',
  'selenium',
  'vitamin_a',
  'vitamin_d',
  'vitamin_e',
  'vitamin_k',
  'b12',
  'folate',
  'omega3',
  'fiber',
];

const PREF_NUTRIENT_LABELS = {
  calcium:   { zh: '\u9499', en: 'Calcium' },
  iron:      { zh: '\u94c1', en: 'Iron' },
  zinc:      { zh: '\u950c', en: 'Zinc' },
  iodine:    { zh: '\u7898', en: 'Iodine' },
  selenium:  { zh: '\u7852', en: 'Selenium' },
  vitamin_a: { zh: '\u7ef4\u751f\u7d20 A', en: 'Vitamin A' },
  vitamin_d: { zh: '\u7ef4\u751f\u7d20 D', en: 'Vitamin D' },
  vitamin_e: { zh: '\u7ef4\u751f\u7d20 E', en: 'Vitamin E' },
  vitamin_k: { zh: '\u7ef4\u751f\u7d20 K', en: 'Vitamin K' },
  b12:       { zh: '\u7ef4\u751f\u7d20 B12', en: 'Vitamin B12' },
  folate:    { zh: '\u53f6\u9178', en: 'Folate' },
  omega3:    { zh: 'Omega-3', en: 'Omega-3' },
  fiber:     { zh: '\u81b3\u98df\u7ea4\u7ef4', en: 'Dietary fiber' },
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
  red_beans:               { zh: '红豆',       en: 'Adzuki Beans' },
  mung_beans:              { zh: '绿豆',       en: 'Mung Beans' },
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
  onion:                   { zh: '洋葱',       en: 'Onion' },
  green_pepper:            { zh: '青椒',       en: 'Green Pepper' },
  bell_pepper:             { zh: '彩椒',       en: 'Bell Pepper' },
  you_cai:                 { zh: '油菜',       en: 'Yu Choy' },
  baby_napa_cabbage:       { zh: '娃娃菜',     en: 'Baby Napa Cabbage' },
  konjac:                  { zh: '魔芋',       en: 'Konjac' },
  celtuce:                 { zh: '莴笋',       en: 'Celtuce' },
  zucchini:                { zh: '西葫芦',     en: 'Zucchini' },
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
  basa_fish:               { zh: '巴沙鱼/龙利鱼', en: 'Basa Fish' },
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
  mackerel:                { zh: '青花鱼/鲐鱼', en: 'Mackerel' },
  sardine:                 { zh: '沙丁鱼',     en: 'Sardine' },
  oyster:                  { zh: '牡蛎',       en: 'Oyster' },
  clam:                    { zh: '蛤蜊',       en: 'Clam' },
  mussel:                  { zh: '青口',       en: 'Mussel' },
  scallop:                 { zh: '扇贝',       en: 'Scallop' },
  dried_shrimp:            { zh: '虾皮',       en: 'Dried Shrimp' },
  // soy
  tofu_firm:               { zh: '老豆腐',     en: 'Firm Tofu' },
  tofu_soft:               { zh: '嫩豆腐',     en: 'Soft Tofu' },
  dried_tofu:              { zh: '豆腐干',     en: 'Dried Tofu' },
  soy_milk:                { zh: '豆浆',       en: 'Soy Milk' },
  natto:                   { zh: '纳豆',       en: 'Natto' },
  tempeh:                  { zh: '天贝',       en: 'Tempeh' },
  edamame:                 { zh: '毛豆',       en: 'Edamame' },
  black_beans:             { zh: '黑豆',       en: 'Black Soybeans' },
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
  sesame_paste:            { zh: '芝麻酱',     en: 'Sesame Paste' },
  olive_oil:               { zh: '橄榄油',     en: 'Olive Oil' },
  cooking_oil:             { zh: '其他炒菜油', en: 'Other Cooking Oil' },
};
