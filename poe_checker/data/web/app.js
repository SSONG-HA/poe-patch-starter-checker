/* ==========================================================================
   PoE 패치노트 스타터 검증기 v1.3.0 — 대시보드 프론트엔드
   외부 라이브러리 없이 동작하는 바닐라 JS. 로컬 서버(/api/*)와 통신한다.
   ========================================================================== */
(() => {
  'use strict';

  // ------------------------------------------------------------------ helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (v) => String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, (c) => ESC[c]);
  const num = (v) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString('ko-KR') : '–');
  const icon = (id, size = 15) =>
    `<svg width="${size}" height="${size}" aria-hidden="true"><use href="#${id}"/></svg>`;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  const VERDICT = {
    green: { text: '무사통과', emoji: '🟢' },
    yellow: { text: '일부 조정', emoji: '🟡' },
    red: { text: '핵심 너프', emoji: '🔴' },
  };

  const SLOT_KO = {
    'Weapon 1': '무기 1', 'Weapon 2': '무기 2', Weapon: '무기', Offhand: '보조 장비',
    Helmet: '투구', 'Body Armour': '갑옷', Gloves: '장갑', Boots: '장화', Belt: '허리띠',
    Amulet: '목걸이', Ring: '반지', 'Ring 1': '반지 1', 'Ring 2': '반지 2',
    'Flask 1': '플라스크 1', 'Flask 2': '플라스크 2', 'Flask 3': '플라스크 3',
    'Flask 4': '플라스크 4', 'Flask 5': '플라스크 5',
  };

  const FIT_FIELDS = [
    ['mapping', '맵핑'], ['bossing', '보스'], ['tankiness', '탱킹'],
    ['budget', '저자본'], ['ease', '편의'],
  ];

  const PRESETS = [
    { key: 'allrounder', label: '올라운더' },
    { key: 'mapping', label: '맵핑' },
    { key: 'bossing', label: '보스' },
    { key: 'budget', label: '저자본' },
    { key: 'ease', label: '편의성' },
  ];

  // ------------------------------------------------------------------ state
  const S = {
    version: '',
    game: 'poe1',
    games: [],
    library: null,
    sync: null,
    notes: [],
    notesError: '',
    result: null,
    summary: null,
    builds: [],
    buildsMeta: { count: 0, builtin: 0, custom: 0, library_path: '' },
    view: 'dashboard',
    preset: 'allrounder',
    survival: { filter: 'all', q: '', id: null },
    guide: { id: null, data: null, stage: null, itemSet: null, q: '' },
    buffs: { min: 3, top: 15, kind: '', selected: 0 },
    busy: 0,
    lastStatus: '준비됨',
  };

  // ------------------------------------------------------------------ api
  async function api(path, body) {
    const opts = { headers: { 'X-App-Token': window.APP_TOKEN || '' } };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (err) {
      throw new Error('로컬 서버와 연결이 끊겼습니다. 앱을 다시 실행해 주세요.');
    }
    let data = null;
    try {
      data = await res.json();
    } catch (err) {
      throw new Error(`서버 응답을 읽지 못했습니다 (HTTP ${res.status})`);
    }
    if (!res.ok || data.ok === false) {
      throw new Error((data && data.error) || `요청 실패 (HTTP ${res.status})`);
    }
    return data;
  }

  // ------------------------------------------------------------------ ui bits
  function toast(message, kind = 'info', ms = 4600) {
    const host = $('#toasts');
    const box = document.createElement('div');
    box.className = `toast ${kind}`;
    const ic = kind === 'error' ? 'i-alert' : kind === 'ok' ? 'i-check' : 'i-info';
    box.innerHTML = `<span class="t-ic">${icon(ic)}</span><div class="t-body">${esc(message)}</div>`;
    host.appendChild(box);
    setTimeout(() => {
      box.classList.add('out');
      setTimeout(() => box.remove(), 220);
    }, ms);
  }

  function setStatus(text, kind = '') {
    S.lastStatus = text;
    const chip = $('#chip-status-text');
    if (chip) chip.textContent = text;
    const holder = $('#chip-status');
    if (holder) holder.classList.toggle('warn', kind === 'error');
  }

  function busy(on, message = '') {
    S.busy = Math.max(0, S.busy + (on ? 1 : -1));
    const active = S.busy > 0;
    $('#progress-line').classList.toggle('on', active);
    const btn = $('#btn-analyze');
    btn.classList.toggle('loading', active);
    btn.disabled = active;
    const load = $('#ticker-loading');
    if (load) load.style.display = active ? 'inline-flex' : 'none';
    if (message) setStatus(message);
    if (!active && S.busy === 0) {
      $('#progress-line').classList.remove('on');
    }
  }

  function ticker(main, opts = {}) {
    const el = $('#ticker-main');
    el.textContent = main;
    el.classList.toggle('t-warn', !!opts.warn);
    if (opts.entry !== undefined) $('#ticker-entry').textContent = opts.entry;
    if (opts.version !== undefined) $('#ticker-version').textContent = opts.version;
  }

  const emptyState = (title, desc, ic = 'i-info') => `
    <div class="empty">
      <div class="e-icon">${icon(ic, 22)}</div>
      <h4>${esc(title)}</h4>
      <p>${esc(desc)}</p>
    </div>`;

  function stars(value) {
    const v = clamp(Number(value) || 0, 0, 5);
    return `<span class="stars" title="${v}/5">${[1, 2, 3, 4, 5]
      .map((i) => `<i class="${i <= v ? 'on' : ''}"></i>`)
      .join('')}</span>`;
  }

  function verdictPill(verdict) {
    const v = VERDICT[verdict] || { text: verdict || '미확인' };
    return `<span class="pill ${verdict}">${v.emoji || ''} ${esc(v.text)}</span>`;
  }

  function scoreColor(v) {
    if (v >= 4) return 'var(--green)';
    if (v >= 3) return 'var(--yellow)';
    return 'var(--red)';
  }

  // ------------------------------------------------------------------ modal
  let escHandler = null;

  function closeModal() {
    $('#modal-root').innerHTML = '';
    if (escHandler) {
      document.removeEventListener('keydown', escHandler);
      escHandler = null;
    }
  }

  function openModal({ title, body, footer = '', small = false }) {
    const root = $('#modal-root');
    root.innerHTML = `
      <div class="modal-backdrop">
        <div class="modal ${small ? 'small' : ''}" role="dialog" aria-modal="true">
          <div class="modal-head">
            <h3>${esc(title)}</h3>
            <button class="btn ghost icon x" data-action="close-modal" title="닫기">${icon('i-close')}</button>
          </div>
          <div class="modal-body">${body}</div>
          ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
        </div>
      </div>`;
    const back = $('.modal-backdrop', root);
    back.addEventListener('mousedown', (e) => {
      if (e.target === back) closeModal();
    });
    escHandler = (e) => {
      if (e.key === 'Escape') closeModal();
    };
    document.addEventListener('keydown', escHandler);
  }

  function confirmModal(title, message, okLabel = '확인') {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      openModal({
        title,
        small: true,
        body: `<p style="font-size:12.5px;color:var(--text-soft);line-height:1.65">${esc(message)}</p>`,
        footer: `<button class="btn ghost" id="modal-cancel">취소</button>
                 <button class="btn primary" id="modal-confirm">${esc(okLabel)}</button>`,
      });
      $('#modal-confirm').addEventListener('click', () => {
        finish(true);
        closeModal();
      });
      $('#modal-cancel').addEventListener('click', () => {
        finish(false);
        closeModal();
      });
      // X 버튼·바깥 클릭·ESC 로 닫힌 경우
      const observer = new MutationObserver(() => {
        if (!$('#modal-root').innerHTML) {
          observer.disconnect();
          finish(false);
        }
      });
      observer.observe($('#modal-root'), { childList: true });
    });
  }

  // ------------------------------------------------------------------ views
  function showView(name) {
    S.view = name;
    $$('.view').forEach((v) => v.classList.toggle('active', v.dataset.view === name));
    $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.nav === name));
    const content = $('#content');
    if (content) content.scrollTop = 0;
  }

  // ------------------------------------------------------------------ header
  function renderGames() {
    const host = $('#game-switch');
    host.innerHTML = S.games
      .map(
        (g) => `<button data-action="set-game" data-game="${esc(g.key)}"
          class="${g.key === S.game ? 'active' : ''}" role="tab"
          aria-selected="${g.key === S.game}">${esc(g.short)}</button>`
      )
      .join('');
  }

  function renderMeta() {
    const counts = (S.library && S.library.counts) || {};
    $('#chip-library-count').textContent = num(counts.total || 0);
    const game = S.games.find((g) => g.key === S.game);
    $('#foot-game').textContent = game ? game.label : S.game;
    const meta = S.buildsMeta;
    $('#foot-library').textContent = `스타터 ${num(meta.count || 0)}개 · 내 빌드 ${num(meta.custom || 0)}개`;
    $('#foot-path').textContent = meta.library_path || (S.library && S.library.path) || '';
    $('#manage-count').textContent = `내 빌드 ${num(meta.custom || 0)}`;
  }

  function renderSyncBadge() {
    const sync = S.sync || {};
    const updated = (sync.updated || '').trim();
    const badge = $('#sync-badge');
    badge.textContent = updated ? updated.replace(/^v/i, '') : '동봉';
    const btn = $('#btn-sync');
    btn.title = `원격 카탈로그에서 스타터 최신화${sync.catalog ? `\n${sync.catalog}` : ''}` +
      (sync.last_sync ? `\n마지막 동기화: ${sync.last_sync}` : '');
  }

  // ------------------------------------------------------------------ notes
  async function loadNotes(refresh = false) {
    const sel = $('#patch-select');
    sel.disabled = true;
    try {
      const data = await api(`/api/news?game=${encodeURIComponent(S.game)}&refresh=${refresh ? 1 : 0}`);
      S.notes = data.refs || [];
      S.notesError = data.error || '';
      if (!S.notes.length) {
        sel.innerHTML = '<option value="">패치노트를 찾지 못했습니다</option>';
        ticker(
          S.notesError
            ? `패치노트 목록을 가져오지 못했습니다: ${S.notesError}`
            : '패치노트 목록이 비어 있습니다. 「붙여넣기」로 본문을 넣어 검사할 수 있습니다.',
          { warn: !!S.notesError }
        );
      } else {
        const previous = sel.value;
        sel.innerHTML = S.notes
          .map((r) => `<option value="${esc(r.url)}">${esc(r.display)}</option>`)
          .join('');
        if (previous && S.notes.some((r) => r.url === previous)) sel.value = previous;
        if (!S.result) {
          ticker(`최신 패치노트 ${S.notes.length}건을 불러왔습니다. 「분석 실행」을 눌러 주세요.`, {
            entry: '항목 –',
            version: '버전 –',
          });
        }
      }
      sel.disabled = false;
      if (refresh) toast(`패치노트 목록을 새로고침했습니다 (${S.notes.length}건)`, 'ok');
    } catch (err) {
      S.notes = [];
      sel.innerHTML = '<option value="">패치노트를 불러오지 못했습니다</option>';
      ticker(err.message, { warn: true });
      if (refresh) toast(err.message, 'error');
    } finally {
      sel.disabled = false;
    }
    updateNavCounts();
  }

  // ------------------------------------------------------------------ builds
  async function loadBuilds() {
    try {
      const data = await api(`/api/builds?game=${encodeURIComponent(S.game)}`);
      S.builds = data.builds || [];
      S.buildsMeta = {
        count: data.count || 0,
        builtin: data.builtin || 0,
        custom: data.custom || 0,
        library_path: data.library_path || '',
      };
      renderMeta();
      renderGuideList();
      renderCustomList();
      updateNavCounts();
      if (!S.guide.id && S.builds.length) {
        const preferred = S.builds.find((b) => b.custom) || S.builds[0];
        S.guide.id = preferred.id;
      }
      renderGuideList();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // ------------------------------------------------------------------ analyze
  async function analyze(textOverride) {
    if (S.busy > 0) return;
    const body = { game: S.game, top: 15, min_buff: 3 };
    if (textOverride) {
      body.text = textOverride;
    } else {
      const url = $('#patch-select').value;
      if (!url) {
        toast('패치노트를 선택하거나 「붙여넣기」로 본문을 넣어 주세요.', 'error');
        return;
      }
      body.url = url;
    }
    busy(true, textOverride ? '붙여넣은 패치노트를 분석하는 중…' : '패치노트를 내려받아 분석하는 중…');
    try {
      const data = await api('/api/analyze', body);
      applyResult(data);
      const k = data.result.kpi;
      toast(`검사 완료 — 🟢 ${k.green} · 🟡 ${k.yellow} · 🔴 ${k.red} · 상향 ${k.buffs}`, 'ok');
      setStatus(`분석 완료 ${new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`);
    } catch (err) {
      toast(err.message, 'error', 7000);
      setStatus('분석 실패', 'error');
    } finally {
      busy(false);
    }
  }

  function applyResult(data) {
    if (!data || !data.result) return;
    S.result = data.result;
    S.summary = data.summary;
    const ids = new Set(S.result.verdicts.map((v) => v.id));
    if (!S.survival.id || !ids.has(S.survival.id)) {
      S.survival.id = (S.result.verdicts.find((v) => v.verdict === 'red') || S.result.verdicts[0] || {}).id || null;
    }
    S.buffs.selected = 0;
    renderDashboard();
    renderSurvival();
    renderBuffs();
    renderGuideList();
    updateTicker();
    updateNavCounts();
    $('#dash-source').textContent = S.result.title || S.result.source || '패치노트';
    $('#dash-source').title = S.result.source || '';
  }

  function updateTicker() {
    if (!S.result) return;
    const k = S.result.kpi;
    const warn = (S.result.warnings || [])[0];
    ticker(
      `${S.result.title || S.result.source || '패치노트'} · ${num(S.result.entry_count)}개 항목 분석 · ` +
        `🟢 ${k.green} / 🟡 ${k.yellow} / 🔴 ${k.red}` + (warn ? ` · ⚠ ${warn}` : ''),
      {
        warn: !!warn,
        entry: `항목 ${num(S.result.entry_count)}`,
        version: S.result.version_hint ? `패치 ${S.result.version_hint}` : (S.game === 'poe2' ? 'PoE2 0.5' : 'PoE1 3.30'),
      }
    );
  }

  function updateNavCounts() {
    const total = S.result ? S.result.verdicts.length : 0;
    $('#nav-dash-count').textContent = S.result ? total : '–';
    $('#nav-survival-count').textContent = S.result ? total : '–';
    $('#nav-guide-count').textContent = S.buildsMeta.count || '–';
    $('#nav-buff-count').textContent = S.result ? S.result.kpi.buffs : '–';
  }

  // ------------------------------------------------------------------ dashboard
  function renderDashboard() {
    renderKpi();
    renderPresets();
    renderRecs();
    renderAlerts();
    renderDashboardBuffs();
  }

  function renderKpi() {
    const host = $('#kpi-grid');
    const k = S.result ? S.result.kpi : null;
    const total = k ? Math.max(1, k.total) : 1;
    const card = (label, value, cls, foot, bar) => `
      <div class="kpi" style="--accent:var(--${cls})">
        <div class="kpi-top"><span>${label}</span><span class="icon-dot"></span></div>
        <div class="kpi-num">${value === null ? '–' : num(value)}${value === null ? '' : '<small>개</small>'}</div>
        <div class="kpi-foot">${foot}</div>
        <div class="kpi-bar"><span style="width:${k ? bar : 0}%"></span></div>
      </div>`;
    host.innerHTML = [
      card('🟢 생존', k ? k.green : null, 'green', k ? `전체 ${num(k.total)}개 중 ${Math.round((k.green / total) * 100)}%` : '분석을 실행하면 채워집니다', k ? (k.green / total) * 100 : 0),
      card('🟡 주의', k ? k.yellow : null, 'yellow', k ? '수치 조정·일부 변경 포함' : '분석 대기', k ? (k.yellow / total) * 100 : 0),
      card('🔴 위험', k ? k.red : null, 'red', k ? (k.red ? '핵심 스킬 너프 — 대안 검토' : '핵심 너프 없음') : '분석 대기', k ? (k.red / total) * 100 : 0),
      card('⬆ 상향', k ? k.buffs : null, 'gold', k ? '이번 패치에서 오른 항목' : '분석 대기', k ? Math.min(100, (k.buffs / Math.max(12, total)) * 100) : 0),
    ].join('');
  }

  function renderPresets() {
    const host = $('#fit-presets');
    host.innerHTML = PRESETS.map(
      (p) => `<button class="chip ${S.preset === p.key ? 'active' : ''}" data-action="preset" data-key="${p.key}">${p.label}</button>`
    ).join('');
  }

  function easeReason(entry) {
    const fit = entry.fit || {};
    const bits = [`편의 ${fit.ease}`, `저자본 ${fit.budget}`, `탱킹 ${fit.tankiness}`];
    const tags = (fit.tags || []).slice(0, 2).join(' · ');
    const patch = entry.buffs || entry.nerfs ? `패치 상향 ${entry.buffs} · 너프 ${entry.nerfs}` : '패치 영향 없음';
    return `${bits.join(' · ')} · ${patch}${tags ? ` · ${tags}` : ''}`;
  }

  function presetRows() {
    if (!S.result || !S.result.recommend) return [];
    const rec = S.result.recommend;
    if (S.preset === 'ease') {
      const rows = (rec.entries || []).filter((e) => !e.error).slice();
      rows.sort((a, b) => (b.fit.ease - a.fit.ease) || (b.fit.budget - a.fit.budget) || (b.scores.allrounder - a.scores.allrounder));
      return rows.map((e) => ({ entry: e, score: e.fit.ease, max: 5 }));
    }
    const cat = (rec.categories && rec.categories[S.preset]) || { rows: [] };
    return (cat.rows || []).map((e) => ({ entry: e, score: e.scores[S.preset] || 0, max: 5 }));
  }

  function renderRecs() {
    const host = $('#rec-grid');
    const sub = $('#rec-sub');
    if (!S.result) {
      host.innerHTML = emptyState(
        '아직 분석 결과가 없습니다',
        '위에서 패치노트를 고르고 「분석 실행」을 누르면 콘텐츠 적합도와 패치 보정을 합친 추천 TOP 이 채워집니다.',
        'i-grid'
      );
      sub.textContent = '콘텐츠 적합도 × 패치 보정 점수';
      return;
    }
    const preset = PRESETS.find((p) => p.key === S.preset) || PRESETS[0];
    sub.textContent =
      S.preset === 'ease'
        ? '손이 편한 순 (편의 → 저자본 → 올라운더)'
        : `${preset.label} 적합도 × 이번 패치 보정`;
    const rows = presetRows().slice(0, 12);
    if (!rows.length) {
      host.innerHTML = emptyState('추천할 빌드가 없습니다', '이 게임의 스타터가 라이브러리에 없거나 모두 읽지 못했습니다.', 'i-alert');
      return;
    }
    host.innerHTML = rows
      .map(({ entry, score, max }, i) => {
        const pct = clamp((score / max) * 100, 4, 100);
        const fitBits = FIT_FIELDS.map(
          ([k, label]) => `<span>${label} ${stars(entry.fit[k])}</span>`
        ).join('');
        const tags = (entry.fit.tags || []).slice(0, 3).map((t) => `<span class="tag">${esc(t)}</span>`).join('');
        return `
          <article class="rec-card" data-action="open-guide" data-id="${esc(entry.id)}" title="가이드 열기">
            <span class="rec-rank">#${i + 1}</span>
            <div class="rec-gauge" style="--p:${pct}"><b>${S.preset === 'ease' ? Number(score).toFixed(0) : Number(score).toFixed(2)}</b></div>
            <div class="rec-body">
              <div class="rec-name">${esc(entry.name)}</div>
              <div class="rec-meta">${verdictPill(entry.verdict)}
                ${entry.kind ? `<span>${esc(entry.kind)}</span>` : ''}
                ${entry.origin ? `<span>· ${esc(entry.origin)}</span>` : ''}
              </div>
              <div class="rec-reason">${esc(S.preset === 'ease' ? easeReason(entry) : (entry.reasons[S.preset] || entry.reasons.allrounder || ''))}</div>
              <div class="rec-fit">${fitBits}</div>
              <div class="rec-meta" style="margin-top:6px">${tags}</div>
            </div>
          </article>`;
      })
      .join('');
  }

  function renderAlerts() {
    const host = $('#dash-alerts');
    const count = $('#alert-count');
    if (!S.result) {
      count.textContent = '';
      host.innerHTML = emptyState('분석 대기', '패치노트를 분석하면 위험·주의 빌드가 여기에 모입니다.', 'i-alert');
      return;
    }
    const risky = S.result.verdicts
      .filter((v) => v.verdict !== 'green')
      .sort((a, b) => (a.verdict === 'red' ? -1 : 1) - (b.verdict === 'red' ? -1 : 1) || b.nerfs - a.nerfs);
    count.textContent = risky.length ? `${risky.length}건` : '이상 없음';
    if (!risky.length) {
      host.innerHTML = emptyState('위험 신호 없음', '이번 패치에서 핵심 스킬 너프를 맞은 스타터가 없습니다.', 'i-check');
      return;
    }
    host.innerHTML = risky
      .slice(0, 7)
      .map(
        (v) => `<div class="compact-row" data-action="open-survival" data-id="${esc(v.id)}">
          <span class="dot ${v.verdict}" style="width:8px;height:8px;border-radius:50%;background:var(--${v.verdict})"></span>
          <span class="c-name">${esc(v.name)}</span>
          <span class="c-sub">${esc(v.headline)}</span>
          <span class="c-num">${v.nerfs ? `−${v.nerfs}` : '조정'}</span>
        </div>`
      )
      .join('');
  }

  function renderDashboardBuffs() {
    const host = $('#dash-buffs');
    const count = $('#buff-count');
    if (!S.result) {
      count.textContent = '';
      host.innerHTML = emptyState('분석 대기', '패치노트를 분석하면 크게 상향된 항목이 여기에 나옵니다.', 'i-bolt');
      return;
    }
    const rows = (S.result.buffs || []).slice(0, 7);
    count.textContent = rows.length ? `상위 ${rows.length}건` : '없음';
    if (!rows.length) {
      host.innerHTML = emptyState('상향 항목 없음', '수치 상향·정성 상향 항목을 찾지 못했습니다.', 'i-bolt');
      return;
    }
    host.innerHTML = rows
      .map(
        (b, i) => `<div class="compact-row" data-action="open-buff" data-index="${i}">
          <span class="c-num" style="color:var(--muted-2)">${String(i + 1).padStart(2, '0')}</span>
          <span class="c-name">${esc(b.name)}${b.korean ? ` <span class="muted" style="font-size:10px">${esc(b.korean)}</span>` : ''}</span>
          <span class="c-sub">${esc(b.kind)}</span>
          <span class="c-num" style="color:var(--green)">${b.qualitative ? '정성' : `${b.score > 0 ? '+' : ''}${b.score.toFixed(1)}%`}</span>
        </div>`
      )
      .join('');
  }

  // ------------------------------------------------------------------ survival
  function renderSurvival() {
    renderSurvivalList();
    renderSurvivalDetail();
    const sum = $('#survival-summary');
    sum.textContent = S.result
      ? `🔴 ${S.result.kpi.red} · 🟡 ${S.result.kpi.yellow} · 🟢 ${S.result.kpi.green}`
      : '';
  }

  function filteredVerdicts() {
    if (!S.result) return [];
    const q = S.survival.q.trim().toLowerCase();
    return S.result.verdicts.filter((v) => {
      if (S.survival.filter === 'custom' && !v.mine) return false;
      if (['green', 'yellow', 'red'].includes(S.survival.filter) && v.verdict !== S.survival.filter) return false;
      if (!q) return true;
      return (
        v.name.toLowerCase().includes(q) ||
        (v.class || '').toLowerCase().includes(q) ||
        (v.ascendancy || '').toLowerCase().includes(q) ||
        (v.tags || []).some((t) => t.name.toLowerCase().includes(q))
      );
    });
  }

  function renderSurvivalList() {
    const host = $('#survival-list');
    const filters = $('#survival-filters');
    const k = S.result ? S.result.kpi : null;
    const defs = [
      ['all', '전체', k ? k.total : ''],
      ['green', '🟢', k ? k.green : ''],
      ['yellow', '🟡', k ? k.yellow : ''],
      ['red', '🔴', k ? k.red : ''],
      ['custom', '내 빌드', S.result ? S.result.verdicts.filter((v) => v.mine).length : ''],
    ];
    filters.innerHTML = defs
      .map(
        ([key, label, n]) =>
          `<button class="chip ${S.survival.filter === key ? 'active' : ''}" data-action="survival-filter" data-key="${key}">${label}${n !== '' ? ` <span class="n">${n}</span>` : ''}</button>`
      )
      .join('');
    if (!S.result) {
      host.innerHTML = emptyState('분석 대기', '패치노트를 분석하면 빌드별 생존 판정이 표시됩니다.', 'i-shield');
      return;
    }
    const rows = filteredVerdicts();
    if (!rows.length) {
      host.innerHTML = emptyState('조건에 맞는 빌드가 없습니다', '검색어나 필터를 바꿔 보세요.', 'i-search');
      return;
    }
    host.innerHTML = rows
      .map(
        (v) => `<div class="row ${S.survival.id === v.id ? 'active' : ''}" data-action="survival-select" data-id="${esc(v.id)}">
          <span class="dot ${v.verdict}"></span>
          <div class="row-main">
            <div class="row-title">${esc(v.name)}${v.mine ? ' <span class="pill gold" style="height:17px;font-size:9px">내 빌드</span>' : ''}</div>
            <div class="row-sub">${esc(v.headline)}</div>
          </div>
          <div class="row-side">
            <div class="sc">${v.nerfs ? `−${v.nerfs}` : v.buffs ? `+${v.buffs}` : '0'}</div>
            <div>${v.level ? `${v.level}레벨` : '–'}</div>
          </div>
        </div>`
      )
      .join('');
  }

  function renderSurvivalDetail() {
    const host = $('#survival-detail');
    if (!S.result) {
      host.innerHTML = emptyState('빌드를 선택하세요', '왼쪽 목록에서 빌드를 고르면 적용된 패치 항목과 영향 태그를 보여줍니다.', 'i-shield');
      return;
    }
    const v = S.result.verdicts.find((x) => x.id === S.survival.id) || S.result.verdicts[0];
    if (!v) {
      host.innerHTML = emptyState('빌드가 없습니다', '이 게임의 스타터를 라이브러리에 추가해 주세요.', 'i-shield');
      return;
    }
    const stats = v.stats || {};
    const statBits = [];
    if (stats.dps) statBits.push(['DPS', num(stats.dps), 100]);
    if (stats.dot_dps) statBits.push(['도트 DPS', num(stats.dot_dps), 100]);
    if (stats.ehp) statBits.push(['EHP', num(stats.ehp), 100]);
    const maxStat = Math.max(1, ...statBits.map((x) => Number(String(x[1]).replace(/,/g, '')) || 0));
    const tagSections = ['skill', 'support', 'unique', 'ascendancy', 'keystone']
      .map((type) => {
        const rows = (v.tags || []).filter((t) => t.type === type);
        if (!rows.length) return '';
        const label = rows[0].label;
        return `<div class="section">
          <div class="section-title">${esc(label)} <span class="muted" style="font-size:10px;letter-spacing:0">${rows.length}</span></div>
          <div class="tag-row">
            ${rows
              .map(
                (t) => `<span class="tag ${t.affected || ''}">${esc(t.name)}${t.korean ? `<span class="ko">${esc(t.korean)}</span>` : ''}
                  ${t.affected ? `<b style="font-size:9px">${t.affected === 'nerf' ? '너프' : t.affected === 'buff' ? '상향' : '조정'}</b>` : ''}</span>`
              )
              .join('')}
          </div>
        </div>`;
      })
      .join('');

    const hits = (v.hits || [])
      .map(
        (h) => `<div class="hit">
          <div class="hit-head">
            <span class="hit-kind">${esc(h.kind)}</span>
            <span class="hit-name">${esc(h.name)}${h.korean ? `<span class="ko"> ${esc(h.korean)}</span>` : ''}${h.alias ? `<span class="ko"> (${esc(h.alias)})</span>` : ''}</span>
            <span class="pill ${h.direction === 'buff' ? 'green' : h.direction === 'nerf' ? 'red' : 'yellow'}">${esc(h.direction_label)}${h.score ? ` ${h.score > 0 ? '+' : ''}${h.score.toFixed(1)}%` : ''}</span>
            ${h.core ? '<span class="mini">핵심</span>' : ''}
          </div>
          <ul class="hit-lines">${(h.lines || []).map((line) => `<li>${esc(line)}</li>`).join('')}</ul>
        </div>`
      )
      .join('');

    host.innerHTML = `
      <div class="inspector-inner">
        <div class="insp-head">
          <div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              ${verdictPill(v.verdict)}
              <span class="insp-title">${esc(v.name)}</span>
            </div>
            <div class="insp-sub">${esc([v.ascendancy || v.class, v.level ? `${v.level}레벨` : '', v.tree ? `트리 ${v.tree}` : ''].filter(Boolean).join(' · '))}</div>
          </div>
          <div class="insp-actions">
            <button class="btn small" data-action="open-guide" data-id="${esc(v.id)}">${icon('i-book', 14)} PoB 가이드</button>
            <button class="btn small" data-action="copy-code" data-id="${esc(v.id)}">${icon('i-copy', 14)} 코드 복사</button>
          </div>
        </div>

        <div class="meta-grid">
          <div class="meta-box"><div class="k">판정</div><div class="v">${esc(v.label)}</div></div>
          <div class="meta-box"><div class="k">출처</div><div class="v" title="${esc(v.source_label)}">${esc(v.origin || v.kind || '–')}</div></div>
          <div class="meta-box"><div class="k">너프 / 상향</div><div class="v num">${v.nerfs} / ${v.buffs}</div></div>
          <div class="meta-box"><div class="k">패치 일치</div><div class="v num">${(v.hits || []).length}건</div></div>
        </div>

        ${v.error ? `<div class="patch-banner red" style="margin-top:14px">
          <div class="pb-icon">${icon('i-alert')}</div>
          <div><div class="pb-title">빌드를 읽지 못했습니다</div><div class="pb-desc">${esc(v.error)}</div></div>
        </div>` : ''}

        ${statBits.length ? `<div class="section">
          <div class="section-title">PoB 수치</div>
          <div class="bars">${statBits
            .map(
              ([k, val]) => `<div class="bar-row"><span>${k}</span>
                <div class="bar-track"><div class="bar-fill" style="width:${clamp(((Number(String(val).replace(/,/g, '')) || 0) / maxStat) * 100, 3, 100)}%"></div></div>
                <span class="val">${val}</span></div>`
            )
            .join('')}</div>
        </div>` : ''}

        <div class="section">
          <div class="section-title">한 줄 요약</div>
          <div style="font-size:12.5px;color:var(--text-soft);line-height:1.65">${esc(v.headline)}</div>
        </div>

        ${tagSections}

        <div class="section">
          <div class="section-title">적용된 패치 항목</div>
          ${hits || `<div class="hint">패치노트에서 이 빌드의 구성 요소와 일치하는 항목을 찾지 못했습니다. (변경 없음의 근거로 쓰기 전에 패치노트 형식을 확인하세요.)</div>`}
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ guide
  function renderGuideList() {
    const host = $('#guide-list');
    const q = S.guide.q.trim().toLowerCase();
    const rows = S.builds.filter(
      (b) =>
        !q ||
        b.name.toLowerCase().includes(q) ||
        (b.class || '').toLowerCase().includes(q) ||
        (b.main || '').toLowerCase().includes(q)
    );
    $('#guide-count').textContent = `${rows.length} / ${S.builds.length}`;
    const verdicts = new Map((S.result ? S.result.verdicts : []).map((v) => [v.id, v.verdict]));
    if (!rows.length) {
      host.innerHTML = emptyState('빌드가 없습니다', '「상향 탐지 & 내 스타터」에서 PoB 코드를 추가해 보세요.', 'i-book');
      return;
    }
    host.innerHTML = rows
      .map(
        (b) => `<div class="row ${S.guide.id === b.id ? 'active' : ''}" data-action="guide-select" data-id="${esc(b.id)}">
          <span class="dot ${verdicts.get(b.id) || ''}"></span>
          <div class="row-main">
            <div class="row-title">${esc(b.name)}${b.mine ? ' <span class="pill gold" style="height:17px;font-size:9px">내 빌드</span>' : ''}</div>
            <div class="row-sub">${esc([b.class, b.level ? `${b.level}레벨` : '', b.kind].filter(Boolean).join(' · '))}${b.error ? ' · ⚠ 읽기 오류' : ''}</div>
          </div>
          <div class="row-side"><div class="sc">${esc(b.tree || '')}</div></div>
        </div>`
      )
      .join('');
  }

  async function selectGuide(id) {
    S.guide.id = id;
    S.guide.stage = null;
    S.guide.itemSet = null;
    renderGuideList();
    showView('guide');
    const host = $('#guide-main');
    host.innerHTML = `<div class="inspector-inner"><div class="loading-note"><span class="spinner"></span> ${esc(
      (S.builds.find((b) => b.id === id) || {}).name || '빌드'
    )} 가이드를 만드는 중…</div></div>`;
    try {
      const data = await api(`/api/guide?build_id=${encodeURIComponent(id)}`);
      S.guide.data = data.guide;
      const stages = S.guide.data.stages || [];
      S.guide.stage = stages.length ? stages[0].key : 'basic';
      S.guide.itemSet = preferredItemSet().id || null;
      renderGuide();
      $('#guide-summary').textContent =
        `${S.guide.data.game_label} · 스킬 세트 ${S.guide.data.skill_sets.length} · 장비 세트 ${S.guide.data.item_sets.length}`;
    } catch (err) {
      host.innerHTML = `<div class="inspector-inner">${emptyState('가이드를 만들지 못했습니다', err.message, 'i-alert')}</div>`;
      toast(err.message, 'error');
    }
  }

  function activeStage() {
    const g = S.guide.data;
    if (!g) return null;
    const stages = g.stages || [];
    return stages.find((s) => s.key === S.guide.stage) || stages[0] || null;
  }

  function preferredItemSet() {
    const g = S.guide.data;
    if (!g) return {};
    const stages = g.stages || [];
    const stage = activeStage();
    const sets = (stage && stage.sets) || [];
    const linked = sets.length ? sets[0].linked_items : '';
    return (
      (g.item_sets || []).find((s) => s.id === S.guide.itemSet) ||
      (g.item_sets || []).find((s) => s.id === linked) ||
      (g.item_sets || []).find((s) => stage && s.stage === stage.key) ||
      (g.item_sets || [])[0] ||
      {}
    );
  }

  function gemChip(gem) {
    const color = gem.color || 'white';
    const ko = gem.korean && gem.korean !== gem.name ? `<span class="ko">${esc(gem.korean)}</span>` : '';
    const lv = gem.level_label ? `<span class="lv">${esc(gem.level_label)}</span>` : '';
    const count = Number(gem.count) > 1 ? `<span class="lv">×${gem.count}</span>` : '';
    const corr = gem.corrupted ? '<span class="corr">타락</span>' : '';
    return `<span class="gem ${gem.support ? '' : 'active-gem'} ${gem.enabled ? '' : 'off'}" title="${esc(gem.name)}${gem.korean ? ` (${esc(gem.korean)})` : ''}">
      <span class="socket ${color}"></span><span>${esc(gem.name)}</span>${ko}${lv}${count}${corr}
    </span>`;
  }

  function renderGuide() {
    const host = $('#guide-main');
    const g = S.guide.data;
    if (!g) {
      host.innerHTML = emptyState('빌드를 선택하세요', '왼쪽에서 빌드를 고르면 PoB 가이드가 여기에 렌더링됩니다.', 'i-book');
      return;
    }
    const stage = activeStage();
    const stages = g.stages || [];
    const itemSet = preferredItemSet();
    const patch = g.patch;
    const fit = g.fit;

    const stageTabs = stages.length > 1
      ? `<div class="stage-tabs">${stages
          .map(
            (s) =>
              `<button class="stage-tab ${stage && s.key === stage.key ? 'active' : ''}" data-action="guide-stage" data-key="${esc(s.key)}">${esc(s.label)}
                <span class="muted" style="font-size:10px">${s.sets.length}</span></button>`
          )
          .join('')}</div>`
      : '';

    const linksHtml = ((stage && stage.sets) || [])
      .map((set) => {
        const active = set.active ? ' · 활성 세트' : '';
        const rows = (set.links || [])
          .map(
            (link) => `<div class="link-row ${link.main ? 'main' : ''}">
              <div style="width:74px;flex:0 0 74px;font-size:10.5px;color:var(--muted-2)">${esc(link.slot || (link.main ? '메인 링크' : '보조 링크'))}</div>
              <div class="link-gems">${(link.gems || []).map(gemChip).join('')}</div>
              <div class="link-side">${link.main ? '메인' : ''}${link.enabled === false ? '비활성' : ''}</div>
            </div>`
          )
          .join('');
        return `<div class="set-block">
          <div class="set-head"><span>${esc(set.title || set.name)}</span><span class="set-meta">스킬 세트 ${esc(set.id)}${active}</span></div>
          ${rows || '<div class="hint" style="padding:10px 13px">스킬 링크가 없습니다.</div>'}
        </div>`;
      })
      .join('');

    const itemSetChoices = (g.item_sets || []).length > 1
      ? `<div class="chips" style="margin-bottom:9px">${(g.item_sets || [])
          .map(
            (s) =>
              `<button class="chip ${itemSet.id === s.id ? 'active' : ''}" data-action="guide-itemset" data-id="${esc(s.id)}">${esc(s.title || s.name)}</button>`
          )
          .join('')}</div>`
      : '';

    const slots = ((itemSet && itemSet.items) || [])
      .map((it) => {
        const flags = (it.flags || []).map((f) => `<span>${esc(f)}</span>`).join('');
        const mods = (it.key_mods || []).slice(0, 4);
        const displayName = it.name && !/^new item/i.test(it.name) ? it.name : (it.base || it.name);
        const nameKo = it.korean && it.korean !== displayName ? `<span class="ko">${esc(it.korean)}</span>` : '';
        return `<div class="slot ${it.kind}">
          <div class="s-slot">${esc(SLOT_KO[it.slot] || it.slot)}</div>
          <div class="s-name">${esc(displayName)} ${nameKo}</div>
          ${it.base && it.base !== displayName ? `<div class="s-base">${esc(it.base)}</div>` : ''}
          ${mods.length ? `<ul class="s-mods">${mods.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}
          ${flags ? `<div class="slot-flags">${flags}</div>` : ''}
        </div>`;
      })
      .join('');

    const specHtml = (g.specs || [])
      .map(
        (sp) => `<div class="meta-box"><div class="k">${esc(sp.name)}${sp.tree_version ? ` · ${esc(sp.tree_version)}` : ''}</div>
          <div class="v">${sp.nodes ? `${num(sp.nodes)} 노드` : '–'}</div>
          ${(sp.keystones || []).length ? `<div class="tag-row" style="margin-top:5px">${sp.keystones
            .map((k) => `<span class="tag">${esc(k)}</span>`)
            .join('')}</div>` : ''}</div>`
      )
      .join('');

    const notesHtml = (g.notes_blocks || []).length
      ? (g.notes_blocks || [])
          .map((b) => `<div class="note-block ${b.kind === 'heading' ? 'heading' : ''}">${esc(b.text)}</div>`)
          .join('')
      : g.notes_length
        ? `<div class="note-block">${esc((g.notes || g.note || '').slice(0, 4000) || '메모 본문은 PoB 안에서 확인하세요.')}</div>`
        : '';

    const patchHtml = patch
      ? `<div class="patch-banner ${patch.verdict}">
          <div class="pb-icon">${icon(patch.verdict === 'red' ? 'i-alert' : patch.verdict === 'green' ? 'i-check' : 'i-info')}</div>
          <div>
            <div class="pb-title">${esc(patch.label)} — ${esc(patch.headline)}</div>
            <div class="pb-desc">상향 ${patch.buff_count} · 너프 ${patch.nerf_count}${patch.source ? ` · 근거: ${esc(patch.source)}` : ''}</div>
            ${(patch.advice || []).length ? `<ul class="hit-lines">${patch.advice.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}
          </div>
        </div>`
      : '';

    const fitHtml = fit
      ? `<div class="rec-fit" style="margin-top:10px">${FIT_FIELDS.map(
          ([k, label]) => `<span>${label} ${stars(fit[k])}</span>`
        ).join('')}${(fit.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>`
      : '';

    host.innerHTML = `
      <div class="guide-hero">
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div class="guide-title">${esc(g.name)}</div>
            <div class="guide-sub">${esc([g.game_label, g.headline, g.kind, g.origin].filter(Boolean).join(' · '))}</div>
            <div class="guide-sub" style="margin-top:4px">PoB 코드 ${num(g.pob_code_length)}자${g.source ? ` · <a href="#" data-action="open-source" data-url="${esc(g.source)}">pobb.in 원본</a>` : ''}</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:flex-start">
            ${g.has_pob_code ? `<span class="pill gold">PoB 코드 포함</span>` : '<span class="pill">코드 없음</span>'}
            ${g.tree_version ? `<span class="pill">트리 ${esc(g.tree_version)}</span>` : ''}
          </div>
        </div>
        <div class="guide-hero-actions">
          <button class="btn primary" data-action="copy-code" data-id="${esc(g.build_id)}">${icon('i-copy')} PoB 코드 복사</button>
          <button class="btn" data-action="open-browser" data-id="${esc(g.build_id)}">${icon('i-external')} 브라우저로 크게 보기</button>
          ${g.source ? `<button class="btn ghost" data-action="open-source" data-url="${esc(g.source)}">pobb.in 열기 ${icon('i-external', 13)}</button>` : ''}
        </div>
        ${fitHtml}
      </div>
      <div class="guide-body">
        ${patchHtml}
        ${stageTabs}
        ${linksHtml || '<div class="hint">스킬 세트가 없습니다.</div>'}

        <div class="section">
          <div class="section-title">장비</div>
          ${itemSetChoices}
          <div class="slots">${slots || '<div class="hint">장비 세트가 없습니다.</div>'}</div>
        </div>

        <div class="section">
          <div class="section-title">전직 · 스펙 · 키스톤</div>
          <div class="meta-grid">
            <div class="meta-box"><div class="k">클래스</div><div class="v">${esc(g.class || '–')}</div></div>
            <div class="meta-box"><div class="k">전직</div><div class="v">${esc(g.ascendancy || '–')}</div></div>
            <div class="meta-box"><div class="k">레벨</div><div class="v num">${g.level || '–'}</div></div>
            ${specHtml}
          </div>
          ${(g.keystones || []).length ? `<div class="tag-row" style="margin-top:8px">${g.keystones
            .map((k) => `<span class="tag">${esc(k)}</span>`)
            .join('')}</div>` : ''}
        </div>

        <div class="section">
          <div class="section-title">메모 · 이번 패치 주의사항</div>
          ${notesHtml || '<div class="hint">제작자 메모가 비어 있습니다.</div>'}
          ${(g.warnings || []).length ? `<div class="hint" style="margin-top:8px">⚠ ${esc(g.warnings.join(' / '))}</div>` : ''}
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ buffs
  function filteredBuffs() {
    if (!S.result) return [];
    const min = Number(S.buffs.min) || 0;
    const kind = S.buffs.kind;
    return (S.result.buffs || []).filter(
      (b) => (b.qualitative || b.score >= min) && (!kind || b.kind === kind)
    );
  }

  function renderBuffs() {
    const host = $('#buff-list');
    const kinds = ['', ...new Set((S.result ? S.result.buffs : []).map((b) => b.kind))];
    $('#buff-kind').innerHTML = kinds
      .map((k) => `<option value="${esc(k)}" ${S.buffs.kind === k ? 'selected' : ''}>${k || '전체'}</option>`)
      .join('');
    $('#buff-min').value = S.buffs.min;
    $('#buff-top').value = S.buffs.top;
    $('#buff-summary').textContent = S.result ? `상향 후보 ${S.result.buffs.length}건` : '';

    if (!S.result) {
      host.innerHTML = emptyState('분석 대기', '패치노트를 분석하면 대폭 상향 항목이 순위로 표시됩니다.', 'i-bolt');
      $('#buff-detail').innerHTML = emptyState('항목을 선택하세요', '왼쪽 목록에서 상향 항목을 고르면 근거 문장과 패치 원문을 보여줍니다.', 'i-bolt');
      return;
    }
    const rows = filteredBuffs().slice(0, S.buffs.top);
    if (!rows.length) {
      host.innerHTML = emptyState('조건에 맞는 항목이 없습니다', '최소 상향률을 낮추거나 유형을 전체로 바꿔 보세요.', 'i-bolt');
    } else {
      host.innerHTML = rows
        .map(
          (b, i) => `<div class="buff-row ${S.buffs.selected === i ? 'active' : ''}" data-action="buff-select" data-index="${i}">
            <span class="buff-rank">${String(i + 1).padStart(2, '0')}</span>
            <div class="buff-main">
              <div class="buff-name">${esc(b.name)}${b.korean ? `<span class="ko"> ${esc(b.korean)}</span>` : ''}</div>
              <div class="buff-sub">${esc(b.kind)}${b.occurrences > 1 ? ` · ${b.occurrences}건` : ''}${b.seeds.length ? ` · ${esc(b.seeds.slice(0, 2).join(', '))}` : ''}</div>
            </div>
            <span class="buff-score ${b.mixed ? 'mixed' : ''} ${b.qualitative ? 'qual' : ''}">${b.qualitative ? '정성' : `${b.score > 0 ? '+' : ''}${b.score.toFixed(1)}%`}</span>
          </div>`
        )
        .join('');
    }
    if (S.buffs.selected >= rows.length) S.buffs.selected = 0;
    renderBuffDetail(rows);
  }

  function renderBuffDetail(rows) {
    const host = $('#buff-detail');
    const list = rows || filteredBuffs().slice(0, S.buffs.top);
    const b = list[S.buffs.selected];
    if (!b) {
      host.innerHTML = emptyState('항목을 선택하세요', '왼쪽 목록에서 상향 항목을 고르세요.', 'i-bolt');
      return;
    }
    host.innerHTML = `
      <div class="inspector-inner">
        <div class="insp-head">
          <div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <span class="pill green">${esc(b.direction_label)}</span>
              <span class="insp-title">${esc(b.name)}</span>
            </div>
            <div class="insp-sub">${esc(b.kind)}${b.korean ? ` · ${esc(b.korean)}` : ''}${b.mixed ? ' · 혼합 조정' : ''}</div>
          </div>
          <div class="insp-actions">
            <button class="btn small" data-action="open-source" data-url="${esc(b.poedb)}">poedb ${icon('i-external', 13)}</button>
            ${b.ninja ? `<button class="btn small" data-action="open-source" data-url="${esc(b.ninja)}">poe.ninja ${icon('i-external', 13)}</button>` : ''}
          </div>
        </div>
        <div class="meta-grid">
          <div class="meta-box"><div class="k">최대 상향</div><div class="v num">${b.qualitative ? '정성' : `${b.score > 0 ? '+' : ''}${b.score.toFixed(1)}%`}</div></div>
          <div class="meta-box"><div class="k">합산</div><div class="v num">${b.total > 0 ? '+' : ''}${b.total.toFixed(1)}%</div></div>
          <div class="meta-box"><div class="k">발생</div><div class="v num">${b.occurrences}건</div></div>
          <div class="meta-box"><div class="k">시드 빌드</div><div class="v">${b.seeds.length ? esc(b.seeds.slice(0, 3).join(', ')) : '–'}</div></div>
        </div>
        <div class="section">
          <div class="section-title">근거 문장</div>
          ${(b.evidence || []).length
            ? `<ul class="hit-lines">${b.evidence.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>`
            : '<div class="hint">근거 문장을 추출하지 못했습니다.</div>'}
        </div>
        <div class="section">
          <div class="section-title">패치노트 원문</div>
          ${(b.lines || []).length
            ? `<div class="hit">${b.lines.map((l) => `<div style="font-size:11.5px;color:var(--muted);line-height:1.7">${esc(l)}</div>`).join('')}</div>`
            : '<div class="hint">원문이 없습니다.</div>'}
        </div>
      </div>`;
  }

  function renderCustomList() {
    const host = $('#custom-list');
    const custom = S.builds.filter((b) => b.custom);
    if (!custom.length) {
      host.innerHTML = emptyState('내 빌드가 없습니다', 'pobb.in 주소나 PoB 코드를 붙여넣어 추가하면 여기에 표시됩니다.', 'i-plus');
      return;
    }
    host.innerHTML = custom
      .map(
        (b) => `<div class="custom-item">
          <div class="ci-name" title="${esc(b.name)}">${esc(b.name)}</div>
          <div class="ci-meta">${esc([b.class, b.level ? `${b.level}레벨` : ''].filter(Boolean).join(' · ') || b.kind)}</div>
          <button class="btn small ghost" data-action="open-guide" data-id="${esc(b.id)}">가이드</button>
          <button class="btn small danger" data-action="remove-build" data-id="${esc(b.id)}" data-name="${esc(b.name)}" title="삭제">${icon('i-trash', 13)}</button>
        </div>`
      )
      .join('');
  }

  // ------------------------------------------------------------------ actions
  async function copyText(text, label = '내용을') {
    if (!text) {
      toast('복사할 내용이 없습니다.', 'error');
      return false;
    }
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        toast(`${label} 클립보드에 복사했습니다.`, 'ok');
        return true;
      }
    } catch (err) { /* 폴백 */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      if (ok) {
        toast(`${label} 클립보드에 복사했습니다.`, 'ok');
        return true;
      }
    } catch (err) { /* 폴백 */ }
    try {
      const data = await api('/api/clipboard', { text });
      if (data.copied) {
        toast(`${label} 클립보드에 복사했습니다.`, 'ok');
        return true;
      }
    } catch (err) { /* 아래 실패 안내 */ }
    toast('클립보드에 복사하지 못했습니다. 코드를 직접 선택해 복사해 주세요.', 'error');
    return false;
  }

  async function copyGuideCode(buildId) {
    try {
      const data = await api(`/api/guide/code?build_id=${encodeURIComponent(buildId)}`);
      await copyText(data.code, 'PoB 코드를');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function openExternal(url) {
    if (!url) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
      window.pywebview.api.open_url(url);
      return;
    }
    window.open(url, '_blank', 'noopener');
  }

  async function openGuideBrowser(buildId) {
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_guide) {
        const res = await window.pywebview.api.open_guide(buildId);
        if (res && res.ok) {
          toast(`브라우저로 열었습니다: ${res.path}`, 'ok');
          return;
        }
        if (res && res.error) toast(res.error, 'error');
      }
      const data = await api('/api/guide/open', { build_id: buildId });
      toast(`브라우저로 열었습니다: ${data.path}`, 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function openPatchFile() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_patch_file) {
      try {
        const res = await window.pywebview.api.pick_patch_file();
        if (!res || res.cancelled) return;
        if (res.error) return toast(res.error, 'error');
        openPasteModal(res.text || '', res.name || '패치노트 파일');
      } catch (err) {
        toast(String(err), 'error');
      }
      return;
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.txt,.md,text/plain';
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const text = await file.text();
      openPasteModal(text, file.name);
    });
    input.click();
  }

  async function openBuildFile() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_build_file) {
      try {
        const res = await window.pywebview.api.pick_build_file();
        if (!res || res.cancelled) return;
        if (res.error) return toast(res.error, 'error');
        $('#add-source').value = res.text || '';
        $('#add-name').value = $('#add-name').value || (res.name || '').replace(/\.xml$/i, '');
        $('#add-source').focus();
        toast(`${res.name} 을(를) 읽었습니다. 「추가」를 눌러 라이브러리에 넣으세요.`, 'ok');
      } catch (err) {
        toast(String(err), 'error');
      }
      return;
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xml,.txt,text/xml,application/xml';
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      $('#add-source').value = await file.text();
      $('#add-name').value = $('#add-name').value || file.name.replace(/\.xml$/i, '');
      toast(`${file.name} 을(를) 읽었습니다. 「추가」를 눌러 주세요.`, 'ok');
    });
    input.click();
  }

  function openPasteModal(text = '', sourceName = '붙여넣은 텍스트') {
    openModal({
      title: '패치노트 본문으로 검사',
      body: `
        <div class="field">
          <label>패치노트 본문 (${esc(sourceName)})</label>
          <textarea id="paste-text" rows="14" style="min-height:240px">${esc(text)}</textarea>
        </div>
        <p class="hint">공식 포럼 글을 붙여넣거나 파일 내용을 그대로 넣으면 됩니다. 「이 본문으로 분석」을 누르면 바로 검사합니다.</p>`,
      footer: `<button class="btn ghost" data-action="close-modal">취소</button>
               <button class="btn primary" id="paste-run">${icon('i-play', 14)} 이 본문으로 분석</button>`,
    });
    const area = $('#paste-text');
    setTimeout(() => area && area.focus(), 60);
    $('#paste-run').addEventListener('click', async () => {
      const value = area.value.trim();
      if (!value) {
        toast('패치노트 본문을 붙여넣어 주세요.', 'error');
        return;
      }
      closeModal();
      await analyze(value);
    });
  }

  function openSaveModal() {
    if (!S.result) {
      toast('먼저 검사를 실행해 주세요.', 'error');
      return;
    }
    openModal({
      title: '검사 결과 저장',
      body: `
        <div class="format-list">
          <button class="format-option" data-action="save-format" data-format="md">
            <span class="fo-ext">md</span>
            <span><span class="fo-title">Markdown 리포트</span><br><span class="fo-desc">읽기 좋은 문서 — 노션·위키에 그대로 붙여넣기</span></span>
          </button>
          <button class="format-option" data-action="save-format" data-format="json">
            <span class="fo-ext">json</span>
            <span><span class="fo-title">JSON 데이터</span><br><span class="fo-desc">다른 도구·스크립트로 넘길 때</span></span>
          </button>
          <button class="format-option" data-action="save-format" data-format="txt">
            <span class="fo-ext">txt</span>
            <span><span class="fo-title">텍스트 리포트</span><br><span class="fo-desc">터미널·메모장에서 바로 보는 원문</span></span>
          </button>
        </div>`,
      footer: `<button class="btn ghost" data-action="close-modal">취소</button>`,
    });
  }

  function downloadBlob(content, filename) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  async function saveReport(fmt) {
    closeModal();
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.save_report) {
        const res = await window.pywebview.api.save_report(fmt);
        if (!res || res.cancelled) return;
        if (res.error) return toast(res.error, 'error');
        toast(`저장했습니다: ${res.path}`, 'ok', 7000);
        return;
      }
      if (window.pywebview) {
        const data = await api('/api/export', { format: fmt, save: true });
        toast(`저장했습니다: ${data.path}`, 'ok', 7000);
        return;
      }
      const data = await api('/api/export', { format: fmt });
      downloadBlob(data.content, data.filename);
      toast(`${data.filename} 다운로드를 시작했습니다.`, 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function syncStarters() {
    if (S.busy > 0) return;
    const ok = await confirmModal(
      '스타터 최신화',
      '원격 카탈로그에서 새 시즌 스타터와 PoB 코드를 받아 라이브러리에 병합합니다. 직접 추가한 빌드는 보존됩니다.',
      '최신화 실행'
    );
    if (!ok) return;
    busy(true, '원격 카탈로그에서 스타터를 받는 중…');
    try {
      const data = await api('/api/sync', {});
      S.sync = {
        catalog: data.catalog,
        updated: data.catalog_updated,
        last_sync: new Date().toLocaleString('ko-KR'),
      };
      renderSyncBadge();
      await refreshState();
      await loadBuilds();
      if (data.changed) {
        S.result = null;
        renderDashboard();
        renderSurvival();
        renderBuffs();
      }
      toast(data.summary + (data.changed ? ' · 다시 분석하면 반영됩니다.' : ''), data.errors.length ? 'error' : 'ok', 7000);
      setStatus('스타터 최신화 완료');
    } catch (err) {
      toast(err.message, 'error', 7000);
      setStatus('최신화 실패', 'error');
    } finally {
      busy(false);
    }
  }

  async function addBuild() {
    const source = $('#add-source').value.trim();
    const name = $('#add-name').value.trim();
    if (!source) {
      toast('pobb.in 주소나 PoB 코드를 입력해 주세요.', 'error');
      $('#add-source').focus();
      return;
    }
    const btn = $('#btn-add-build');
    btn.disabled = true;
    busy(true, '빌드를 확인하고 라이브러리에 추가하는 중…');
    try {
      const data = await api('/api/library/add', { source, name, game: S.game });
      $('#add-source').value = '';
      $('#add-name').value = '';
      toast(`추가했습니다: ${data.name}`, 'ok');
      const hadResult = !!S.result;
      await refreshState();
      await loadBuilds();
      S.guide.id = data.id;
      await selectGuide(data.id);
      if (hadResult) {
        S.result = null;
        renderDashboard();
        renderSurvival();
        renderBuffs();
        toast('빌드 목록이 바뀌어 이전 분석 결과를 비웠습니다. 「분석 실행」을 다시 눌러 주세요.', 'info', 6500);
      }
    } catch (err) {
      toast(err.message, 'error', 7000);
    } finally {
      btn.disabled = false;
      busy(false);
    }
  }

  async function removeBuild(id, name) {
    const ok = await confirmModal(
      '빌드 삭제',
      `'${name}' 을(를) 라이브러리에서 삭제할까요? 원본 PoB 파일은 건드리지 않습니다.`,
      '삭제'
    );
    if (!ok) return;
    try {
      await api('/api/library/remove', { id });
      toast(`삭제했습니다: ${name}`, 'ok');
      if (S.guide.id === id) {
        S.guide.id = null;
        S.guide.data = null;
      }
      await loadBuilds();
      if (!S.guide.id && S.builds.length) await selectGuide(S.builds[0].id);
      else renderGuide();
      if (S.result) {
        try {
          const full = await api('/api/result');
          if (full.result) applyResult(full);
        } catch (err) { /* 무시 */ }
      }
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function refreshState() {
    try {
      const st = await api('/api/state');
      S.library = st.library;
      S.sync = st.sync;
      S.games = st.games;
      S.game = st.game;
      S.version = st.app.version;
      renderMeta();
      renderSyncBadge();
      renderGames();
    } catch (err) { /* 상태 갱신 실패는 치명적이지 않다 */ }
  }

  async function setGame(game) {
    if (game === S.game) return;
    S.game = game;
    S.result = null;
    S.summary = null;
    S.survival.id = null;
    S.guide.id = null;
    S.guide.data = null;
    renderGames();
    renderMeta();
    renderDashboard();
    renderSurvival();
    renderBuffs();
    $('#guide-main').innerHTML = emptyState('빌드를 선택하세요', '왼쪽에서 빌드를 고르면 PoB 가이드가 여기에 렌더링됩니다.', 'i-book');
    $('#dash-source').textContent = '패치노트 미선택';
    ticker('패치노트 목록을 불러오는 중…', { entry: '항목 –', version: '버전 –' });
    try {
      await api('/api/game', { game });
    } catch (err) { /* 무시 */ }
    await Promise.all([loadNotes(false), loadBuilds()]);
    if (S.builds.length && !S.guide.id) {
      S.guide.id = S.builds[0].id;
      renderGuideList();
    }
  }

  // ------------------------------------------------------------------ events
  function bind() {
    document.addEventListener('click', (e) => {
      const el = e.target.closest('[data-action]');
      if (!el) return;
      const act = el.dataset.action;
      if (act === 'close-modal') {
        e.preventDefault();
        closeModal();
        return;
      }
      if (act === 'nav') {
        showView(el.dataset.nav);
        if (el.dataset.nav === 'guide' && !S.guide.data && S.guide.id) selectGuide(S.guide.id);
        return;
      }
      if (act === 'set-game') {
        setGame(el.dataset.game);
        return;
      }
      if (act === 'preset') {
        S.preset = el.dataset.key;
        renderPresets();
        renderRecs();
        return;
      }
      if (act === 'open-guide') {
        e.preventDefault();
        selectGuide(el.dataset.id);
        return;
      }
      if (act === 'open-survival') {
        S.survival.id = el.dataset.id;
        S.survival.filter = 'all';
        showView('survival');
        renderSurvival();
        return;
      }
      if (act === 'survival-select') {
        S.survival.id = el.dataset.id;
        renderSurvivalList();
        renderSurvivalDetail();
        return;
      }
      if (act === 'survival-filter') {
        S.survival.filter = el.dataset.key;
        renderSurvivalList();
        return;
      }
      if (act === 'guide-select') {
        selectGuide(el.dataset.id);
        return;
      }
      if (act === 'guide-stage') {
        S.guide.stage = el.dataset.key;
        S.guide.itemSet = null;
        renderGuide();
        return;
      }
      if (act === 'guide-itemset') {
        S.guide.itemSet = el.dataset.id;
        renderGuide();
        return;
      }
      if (act === 'copy-code') {
        copyGuideCode(el.dataset.id);
        return;
      }
      if (act === 'open-browser') {
        openGuideBrowser(el.dataset.id);
        return;
      }
      if (act === 'open-source') {
        e.preventDefault();
        openExternal(el.dataset.url);
        return;
      }
      if (act === 'buff-select') {
        S.buffs.selected = Number(el.dataset.index);
        renderBuffs();
        return;
      }
      if (act === 'open-buff') {
        S.buffs.selected = Number(el.dataset.index);
        S.buffs.min = 0;
        S.buffs.kind = '';
        showView('buffs');
        renderBuffs();
        return;
      }
      if (act === 'save-format') {
        saveReport(el.dataset.format);
        return;
      }
      if (act === 'remove-build') {
        removeBuild(el.dataset.id, el.dataset.name);
        return;
      }
    });

    $$('.nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        showView(btn.dataset.nav);
        if (btn.dataset.nav === 'guide' && !S.guide.data && S.guide.id) selectGuide(S.guide.id);
      });
    });

    $('#btn-refresh-notes').addEventListener('click', () => loadNotes(true));
    $('#btn-analyze').addEventListener('click', () => analyze());
    $('#btn-paste').addEventListener('click', () => openPasteModal('', '붙여넣은 텍스트'));
    $('#btn-open-file').addEventListener('click', openPatchFile);
    $('#btn-save').addEventListener('click', openSaveModal);
    $('#btn-sync').addEventListener('click', syncStarters);
    $('#btn-add-build').addEventListener('click', addBuild);
    $('#btn-pick-build').addEventListener('click', openBuildFile);

    let searchTimer = null;
    $('#survival-search').addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      const value = e.target.value;
      searchTimer = setTimeout(() => {
        S.survival.q = value;
        renderSurvivalList();
      }, 120);
    });
    $('#guide-search').addEventListener('input', (e) => {
      S.guide.q = e.target.value;
      renderGuideList();
    });
    const applyBuffFilters = () => {
      S.buffs.min = Math.max(0, Number($('#buff-min').value) || 0);
      S.buffs.top = clamp(Number($('#buff-top').value) || 15, 1, 100);
      S.buffs.kind = $('#buff-kind').value;
      S.buffs.selected = 0;
      renderBuffs();
    };
    $('#buff-apply').addEventListener('click', applyBuffFilters);
    $('#buff-min').addEventListener('change', applyBuffFilters);
    $('#buff-kind').addEventListener('change', applyBuffFilters);
    $('#buff-top').addEventListener('change', applyBuffFilters);
    $('#add-source').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) addBuild();
    });

    // pywebview 준비 이벤트(있으면)
    window.addEventListener('pywebviewready', () => {
      document.documentElement.classList.add('native');
    });
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    bind();
    renderDashboard();
    renderBuffs();
    $('#guide-main').innerHTML = emptyState('빌드를 선택하세요', '왼쪽에서 빌드를 고르면 PoB 가이드가 여기에 렌더링됩니다.', 'i-book');
    $('#survival-detail').innerHTML = emptyState('빌드를 선택하세요', '패치노트를 분석하면 빌드별 판정이 표시됩니다.', 'i-shield');
    $('#buff-detail').innerHTML = emptyState('항목을 선택하세요', '패치노트를 분석하면 상향 항목이 표시됩니다.', 'i-bolt');
    try {
      const st = await api('/api/state');
      S.version = st.app.version;
      S.games = st.games || [];
      S.game = st.game || 'poe1';
      S.library = st.library;
      S.sync = st.sync;
      renderGames();
      renderMeta();
      renderSyncBadge();
      if (st.result) {
        const full = await api('/api/result');
        if (full.result) applyResult(full);
      }
    } catch (err) {
      toast(err.message, 'error', 9000);
      return;
    }
    await Promise.all([loadNotes(false), loadBuilds()]);
    if (S.builds.length) {
      renderGuideList();
    }
    updateNavCounts();
    setStatus('준비됨');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
