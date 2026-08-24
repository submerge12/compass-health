/* ============================================================
   M09/P6 voice page module — mic capture → transcript + intent
   preview → confirm/correct → commit with receipt.

   Confirmation policy mirrors the backend: modify/pain/unknown
   intents always ask; hedged records ask; clean records commit
   straight away and offer undo-by-text correction.
   ============================================================ */

const VoicePage = {
  _mediaStream: null,
  _lastTranscript: null,
  _lastIntent: null,

  _today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  },

  async render() {
    const el = document.getElementById('page-voice');
    if (!el) return;
    const zh = I18n.lang === 'zh';
    el.innerHTML = `
      <div class="card">
        <h2>${zh ? '语音助手' : 'Voice Assistant'}</h2>
        <p class="muted">${zh
          ? '说出你的记录：饮食、训练组数、身体反馈。音频不会被保存。'
          : 'Speak to log meals, training sets, or body feedback. Audio is never stored.'}</p>
        <div id="voice-controls" style="display:flex; gap:12px; align-items:center;">
          <button id="voice-record-btn" class="btn btn-primary" style="min-width:160px;">🎙️ ${zh ? '按住说话' : 'Hold to speak'}</button>
          <span id="voice-status" class="muted"></span>
        </div>
        <div id="voice-transcript" class="card" style="margin-top:16px; display:none;">
          <strong>${zh ? '识别结果' : 'Transcript'}:</strong> <span id="voice-transcript-text"></span>
          <div id="voice-intent" style="margin-top:8px;"></div>
          <div id="voice-actions" style="margin-top:12px; display:flex; gap:8px;"></div>
        </div>
        <div id="voice-receipt" class="card" style="margin-top:16px; display:none;"></div>
      </div>`;

    const btn = document.getElementById('voice-record-btn');
    const holdEvents = ('webkitSpeechRecognition' in window) ? [] : ['mousedown', 'mouseup'];
    void holdEvents;

    let recording = false;
    let recorder = null;
    let chunks = [];

    btn.addEventListener('mousedown', async () => {
      if (recording) return;
      try {
        this._mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        chunks = [];
        recorder = new MediaRecorder(this._mediaStream);
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = () => this._onRecordingStop(chunks);
        recorder.start();
        recording = true;
        document.getElementById('voice-status').textContent = zh ? '录音中…松开结束' : 'Recording… release to stop';
      } catch (err) {
        document.getElementById('voice-status').textContent =
          zh ? '无法访问麦克风，请检查浏览器权限' : 'Microphone unavailable — check browser permissions';
      }
    });
    btn.addEventListener('mouseup', () => {
      if (!recording) return;
      recorder.stop();
      recording = false;
      this._mediaStream?.getTracks().forEach((track) => track.stop());
      document.getElementById('voice-status').textContent = zh ? '转写中…' : 'Transcribing…';
    });

    // Text fallback is always available (ASR-off resilience, plan §M09).
    const fallback = document.createElement('input');
    fallback.type = 'text';
    fallback.placeholder = zh ? '或直接输入文字指令（如：我中午吃了一碗牛肉面）' : 'Or type an instruction (e.g. I had beef noodles for lunch)';
    fallback.style.cssText = 'margin-top:12px; width:100%;';
    fallback.addEventListener('keydown', async (e) => {
      if (e.key === 'Enter' && fallback.value.trim()) {
        await this._handleTranscript(fallback.value.trim());
        fallback.value = '';
      }
    });
    el.querySelector('.card').appendChild(fallback);
  },

  async _onRecordingStop(chunks) {
    const blob = new Blob(chunks, { type: this._supportedMime() || 'audio/webm' });
    try {
      // Browsers record webm/opus; the backend transcribes via MiMo which wants
      // wav/mp3. If MediaRecorder produced webm we still send it — FastAPI will
      // reject with a clear message and the text input remains the fallback.
      const data = await API.voiceTranscribe(blob, 'zh');
      await this._showResult(data);
    } catch (err) {
      document.getElementById('voice-status').textContent = err.message;
    }
  },

  _supportedMime() {
    for (const mime of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(mime)) return mime;
    }
    return '';
  },

  async handleTextInput(text) {
    await this._handleTranscript(text);
  },

  async _handleTranscript(transcript) {
    try {
      const data = await API.voiceTranscribeText(transcript);
      await this._showResult(data);
    } catch (err) {
      document.getElementById('voice-status').textContent = err.message;
    }
  },

  async _showResult(data) {
    this._lastTranscript = data.transcript;
    this._lastIntent = data.intent;
    document.getElementById('voice-transcript').style.display = '';
    document.getElementById('voice-transcript-text').textContent = data.transcript;

    const intentEl = document.getElementById('voice-intent');
    const intent = data.intent;
    const zh = I18n.lang === 'zh';
    const categoryZh = { query: '查询', record: '记录', modify: '修改', feedback: '反馈', unknown: '未知' };
    intentEl.innerHTML = `
      <span class="badge">${zh ? categoryZh[intent.category] : intent.category}</span>
      ${intent.action ? `<code>${intent.action}</code>` : ''}
      <span class="muted">confidence: ${(intent.confidence * 100).toFixed(0)}%</span>
      ${intent.reply_hint_zh && zh ? `<div class="muted">${intent.reply_hint_zh}</div>` : ''}`;

    const actions = document.getElementById('voice-actions');
    actions.innerHTML = '';

    if (intent.category === 'unknown') {
      const hint = document.createElement('span');
      hint.className = 'muted';
      hint.textContent = zh ? '请换种说法或使用下方文字输入' : 'Try rephrasing or use the text input below';
      actions.appendChild(hint);
      return;
    }

    const needsConfirm = intent.needs_confirmation === true;
    const commitBtn = document.createElement('button');
    commitBtn.className = 'btn btn-primary';
    commitBtn.textContent = needsConfirm
      ? (zh ? '确认并保存' : 'Confirm & save')
      : (zh ? '保存' : 'Save');
    commitBtn.addEventListener('click', () => this._commit(needsConfirm));
    actions.appendChild(commitBtn);

    if (needsConfirm) {
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'btn';
      cancelBtn.textContent = zh ? '放弃' : 'Discard';
      cancelBtn.addEventListener('click', () => {
        document.getElementById('voice-transcript').style.display = 'none';
      });
      actions.appendChild(cancelBtn);
    }
  },

  async _commit(confirmed) {
    const zh = I18n.lang === 'zh';
    try {
      const result = await API.voiceCommit(this._lastTranscript, {
        date: this._today(),
        confirmed,
        idempotencyKey: `ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      });
      const receipt = document.getElementById('voice-receipt');
      receipt.style.display = '';

      if (result.status === 'committed') {
        const isMeal = result.log_id !== null && result.log_id !== undefined;
        receipt.innerHTML = isMeal
          ? `✅ ${zh ? '已保存' : 'Saved'} — log <code>${String(result.log_id).slice(0, 8)}</code>, ${result.kcal ?? '?'} kcal`
          : `✅ ${zh ? '已保存' : 'Saved'}`;
        App?.refreshCurrentPage?.();
      } else if (result.status === 'needs_confirmation') {
        const unmatched = (result.unmatched || []).map((u) =>
          `<li>${u.segment}: ${(u.candidates || []).map((c) => `${c.label}(${c.score})`).join(', ')}</li>`).join('');
        receipt.innerHTML = `${zh ? '需要确认以下内容后重新保存' : 'Confirm these items and re-save'}:<ul>${unmatched}</ul>`;
      } else if (result.status === 'rejected' || result.status === 'unsupported_here') {
        receipt.innerHTML = `⚠️ ${result.hint || (zh ? '该意图请在对应页面操作' : 'Use the matching page for this intent')}`;
      }
    } catch (err) {
      document.getElementById('voice-receipt').style.display = '';
      document.getElementById('voice-receipt').textContent = err.message;
    }
  },
};

if (typeof window !== 'undefined') window.VoicePage = VoicePage;
