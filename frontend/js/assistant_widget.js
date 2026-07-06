/* global API, App, I18n */

const AssistantWidget = {
  _user: null,
  _messages: [],
  _open: false,
  _busy: false,

  init(user) {
    if (!user || user.is_admin) {
      this.hide();
      return;
    }
    this._user = user;
    this._ensureDom();
    this._renderMessages();
    document.body.classList.add('assistant-ready');
    this.show();
  },

  destroy() {
    const root = document.getElementById('assistant-widget');
    if (root) root.remove();
    document.body.classList.remove('assistant-ready', 'assistant-open');
    this._user = null;
    this._messages = [];
    this._open = false;
    this._busy = false;
  },

  hide() {
    const root = document.getElementById('assistant-widget');
    if (root) root.classList.add('hidden');
    document.body.classList.remove('assistant-open');
    this._open = false;
  },

  show() {
    const root = document.getElementById('assistant-widget');
    if (root) root.classList.remove('hidden');
  },

  toggle() {
    this._open ? this.close() : this.open();
  },

  open() {
    this._ensureDom();
    const root = document.getElementById('assistant-widget');
    if (!root) return;
    root.classList.add('open');
    document.body.classList.add('assistant-open');
    this._open = true;
    this._focusInput();
  },

  close() {
    const root = document.getElementById('assistant-widget');
    if (root) root.classList.remove('open');
    document.body.classList.remove('assistant-open');
    this._open = false;
  },

  _ensureDom() {
    if (document.getElementById('assistant-widget')) return;
    const root = document.createElement('div');
    root.id = 'assistant-widget';
    root.className = 'assistant-widget hidden';
    root.innerHTML = `
      <button type="button" class="assistant-fab" aria-label="Nutrition assistant" title="Nutrition assistant">AI</button>
      <section class="assistant-panel" aria-label="Nutrition assistant panel">
        <header class="assistant-panel-head">
          <div>
            <strong>${this._esc(this._label('营养助手', 'Nutrition Assistant'))}</strong>
            <span>${this._esc(this._label('按你的本地数据计算', 'Uses your local data'))}</span>
          </div>
          <button type="button" class="assistant-close" aria-label="Close">×</button>
        </header>
        <div class="assistant-messages" id="assistant-messages"></div>
        <form class="assistant-form" id="assistant-form">
          <textarea id="assistant-input" rows="2" maxlength="1200" placeholder="${this._esc(this._label('问我想吃的东西适不适合减脂...', 'Ask if a food fits fat loss...'))}"></textarea>
          <button type="submit" class="btn btn-primary btn-sm" id="assistant-send">${this._esc(this._label('发送', 'Send'))}</button>
        </form>
      </section>
    `;
    document.body.appendChild(root);
    root.querySelector('.assistant-fab')?.addEventListener('click', () => this.toggle());
    root.querySelector('.assistant-close')?.addEventListener('click', () => this.close());
    root.querySelector('#assistant-form')?.addEventListener('submit', e => {
      e.preventDefault();
      this._send();
    });
    root.querySelector('#assistant-input')?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._send();
      }
    });
  },

  async _send() {
    if (this._busy) return;
    const input = document.getElementById('assistant-input');
    const text = (input?.value || '').trim();
    if (!text) return;
    input.value = '';
    this._messages.push({ role: 'user', content: text });
    this._busy = true;
    this._renderMessages();

    try {
      const payloadMessages = this._messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .slice(-12);
      const res = await API.assistantChat(payloadMessages, this._contextPage());
      const assistantMessage = {
        role: 'assistant',
        content: res.reply || '',
        proposed_actions: res.proposed_actions || [],
      };
      this._messages.push(assistantMessage);
    } catch (err) {
      this._messages.push({
        role: 'assistant',
        content: err.message || this._label('助手暂时不可用。', 'Assistant is temporarily unavailable.'),
        is_error: true,
      });
    } finally {
      this._busy = false;
      this._renderMessages();
      this._focusInput();
    }
  },

  async _confirm(actionId, button) {
    if (!actionId || !button || button.disabled) return;
    button.disabled = true;
    button.textContent = this._label('执行中', 'Applying');
    try {
      await API.confirmAssistantAction(actionId);
      button.textContent = this._label('已完成', 'Done');
      App.showToast(this._label('已应用这项更改', 'Change applied'), 'success');
      this._refreshCurrentPage();
    } catch (err) {
      button.disabled = false;
      button.textContent = this._label('确认', 'Confirm');
      App.showToast(err.message || this._label('确认失败', 'Confirm failed'), 'error');
    }
  },

  _renderMessages() {
    const box = document.getElementById('assistant-messages');
    if (!box) return;
    if (!this._messages.length) {
      box.innerHTML = `
        <div class="assistant-empty">
          ${this._esc(this._label('可以问：我想吃火锅，减脂能吃吗？或者：洋葱炒牛肉适合今天吃吗？', 'Try: Can I eat hot pot during fat loss? Does beef with onion fit today?'))}
        </div>
      `;
      return;
    }
    box.innerHTML = this._messages.map((message, index) => this._renderMessage(message, index)).join('');
    box.querySelectorAll('[data-assistant-action]').forEach(btn => {
      btn.addEventListener('click', () => this._confirm(Number(btn.getAttribute('data-assistant-action')), btn));
    });
    box.scrollTop = box.scrollHeight;
  },

  _renderMessage(message, index) {
    const roleClass = message.role === 'user' ? 'user' : 'assistant';
    const text = this._esc(message.content || '');
    const actions = this._renderActions(message.proposed_actions || []);
    return `
      <div class="assistant-msg ${roleClass}${message.is_error ? ' error' : ''}">
        <div class="assistant-bubble">${text.replace(/\n/g, '<br>') || '&nbsp;'}</div>
        ${actions}
      </div>
    `;
  },

  _renderToolResults(results, index) {
    if (!results.length) return '';
    return `
      <div class="assistant-tool-list">
        ${results.slice(0, 4).map((item, offset) => `
          <details class="assistant-tool-card">
            <summary>${this._esc(this._toolTitle(item.tool || `tool_${offset + 1}`))}</summary>
            <pre>${this._esc(this._compactJson(item.result))}</pre>
          </details>
        `).join('')}
        ${results.length > 4 ? `<div class="assistant-tool-more">+${results.length - 4}</div>` : ''}
      </div>
    `;
  },

  _renderActions(actions) {
    if (!actions.length) return '';
    return `
      <div class="assistant-action-list">
        ${actions.map(action => `
          <div class="assistant-action-card">
            <strong>${this._esc(this._actionTitle(action.action_type))}</strong>
            <span>${this._esc(action.summary || '')}</span>
            <button type="button" class="btn btn-primary btn-sm" data-assistant-action="${Number(action.id)}">
              ${this._esc(this._label('确认', 'Confirm'))}
            </button>
          </div>
        `).join('')}
      </div>
    `;
  },

  _compactJson(value) {
    const text = JSON.stringify(value, null, 2) || '';
    return text.length > 1200 ? `${text.slice(0, 1200)}...` : text;
  },

  _actionTitle(type) {
    const zh = {
      save_nutrition_memory: '保存营养记忆',
      upsert_fixed_breakfast: '更新固定早餐',
      apply_day_plan_slot: '写入单餐计划',
    };
    const en = {
      save_nutrition_memory: 'Save Nutrition Memory',
      upsert_fixed_breakfast: 'Update Fixed Breakfast',
      apply_day_plan_slot: 'Apply Meal Slot',
    };
    const map = (I18n.lang === 'en') ? en : zh;
    return map[type] || type || this._label('待确认操作', 'Pending Action');
  },

  _toolTitle(type) {
    const zh = {
      get_user_targets: '目标与热量',
      search_food_library: '食材匹配',
      calculate_foods: '营养计算',
      audit_food_set: '营养缺口',
      suggest_replacements: '替换建议',
      evaluate_fat_loss_food: '减脂适配',
      preview_day_plan: '单日预览',
      get_week_overview: '本周概览',
      get_nutrition_memory: '营养记忆',
      get_fixed_meals: '固定餐',
      propose_action: '待确认更改',
    };
    const en = {
      get_user_targets: 'Targets',
      search_food_library: 'Food Match',
      calculate_foods: 'Nutrition Calculation',
      audit_food_set: 'Nutrition Gaps',
      suggest_replacements: 'Replacement Ideas',
      evaluate_fat_loss_food: 'Fat-loss Fit',
      preview_day_plan: 'Day Preview',
      get_week_overview: 'Week Overview',
      get_nutrition_memory: 'Nutrition Memory',
      get_fixed_meals: 'Fixed Meals',
      propose_action: 'Pending Change',
    };
    const map = (I18n.lang === 'en') ? en : zh;
    return map[type] || type || this._label('工具结果', 'Tool Result');
  },

  _refreshCurrentPage() {
    if (typeof App === 'undefined' || !App._currentPage) return;
    App.navigate(App._currentPage, {
      navKey: App._currentNavKey,
      planTab: App._currentPage === 'plan' && typeof MealEnginePage !== 'undefined'
        ? MealEnginePage._activeTab
        : undefined,
    });
  },

  _focusInput() {
    setTimeout(() => document.getElementById('assistant-input')?.focus(), 0);
  },

  _contextPage() {
    if (typeof App !== 'undefined' && App._currentPage) return App._currentPage;
    return null;
  },

  _label(zh, en) {
    return I18n.lang === 'en' ? en : zh;
  },

  _esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },
};
