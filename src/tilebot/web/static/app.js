/* Мини-апп плиточника v2 — «объект-холст».
 *
 * Центр приложения — не опросник, а экран объекта: схема-герой сверху, под ней
 * живая спека, где любой параметр правится на месте с мгновенным пересчётом.
 * Ввод сжат в один быстрый экран. Числа считает бэкенд (одно ядро с ботом) — тут
 * ни одной формулы, только показ и PATCH.
 */

const tg = window.Telegram?.WebApp;
const root = document.getElementById('app');

const state = {
  screen: 'list',
  projects: [],
  project: null, // {id, title, result, ...}
  surface: 0, // активная поверхность на холсте
  draft: null, // черновик нового объекта
  paper: null,
  price: null,
  busy: false,
  computing: false,
  lastSchemeUrl: null,
};

// --- сервер ------------------------------------------------------------------

async function api(path, {method = 'GET', body} = {}) {
  const res = await fetch(path, {
    method,
    headers: {'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || ''},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.error || 'Что-то пошло не так на сервере.');
  return data;
}

const measure = (kind, text) => api('/api/measure', {method: 'POST', body: {kind, text}});

/** Обёртка действия-навигации: пока летит запрос, второе нажатие игнорируем.
 * НЕ звать изнутри другого run() — вложенный увидит busy и молча выйдет
 * (баг v1: так терялась кнопка). Внутри обработчика зови просто async-функцию. */
async function run(fn) {
  if (state.busy) { console.warn('run() занят — пропуск'); return; }
  state.busy = true;
  try { await fn(); state.busy = false; render(); }
  catch (e) { state.busy = false; fail(e); }
}

function fail(e) {
  console.error(e);
  render();
  const bar = h(`<div class="error-bar"></div>`);
  bar.firstElementChild.textContent = e.message;
  root.querySelector('.screen')?.prepend(bar);
  tg?.HapticFeedback?.notificationOccurred('error');
}

// --- живой пересчёт холста (debounce + версия против гонок) -------------------

let patchTimer = null;
let patchVersion = 0;
let pendingBody = {};

function livePatch(body) {
  Object.assign(pendingBody, body);
  tg?.HapticFeedback?.impactOccurred('light');
  setComputing(true);
  clearTimeout(patchTimer);
  patchTimer = setTimeout(fireLivePatch, 120);
}

async function fireLivePatch() {
  const body = pendingBody;
  pendingBody = {};
  const v = ++patchVersion;
  try {
    const result = await api(`/api/projects/${state.project.id}`, {method: 'PATCH', body});
    if (v !== patchVersion) return; // пришёл ответ на устаревший параметр — игнор
    state.project.result = result;
    setComputing(false);
    render();
    tg?.HapticFeedback?.notificationOccurred('success');
  } catch (e) {
    if (v !== patchVersion) return;
    setComputing(false);
    fail(e);
  }
}

function setComputing(on) {
  state.computing = on;
  root.querySelector('.scheme')?.classList.toggle('computing', on);
  root.querySelectorAll('.js-num').forEach((n) => n.classList.toggle('computing-dim', on));
}

// --- иконки (SVG, Lucide-стиль) ----------------------------------------------

const ICONS = {
  back: 'M15 18l-6-6 6-6',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  chevron: 'M9 6l6 6-6 6',
  folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  ruler: 'M4 16L16 4l4 4L8 20z M9 11l1 1 M12 8l1 1 M15 5l1 1',
  wallet: 'M3 7a2 2 0 012-2h13a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2z M16 12h3',
  layers: 'M12 3l9 5-9 5-9-5 9-5z M3 13l9 5 9-5',
  grid: 'M4 4h16v16H4z M4 10h16 M10 4v16',
  droplet: 'M12 3s6 6.5 6 11a6 6 0 01-12 0c0-4.5 6-11 6-11z',
  rotate: 'M20 12a8 8 0 11-2.3-5.6 M20 4v4h-4',
  resize: 'M4 9V4h5 M20 15v5h-5 M4 4l6 6 M20 20l-6-6',
  door: 'M4 21V4a1 1 0 011-1h9a1 1 0 011 1v17 M4 21h16 M12 12h.5',
  image: 'M4 5h16v14H4z M4 16l4-4 3 3 4-5 5 6',
  paint: 'M4 12a8 8 0 118 8c-1.5 0-1-2-2.5-2S8 20 6.5 19 4 15.5 4 12z',
  package: 'M12 3l9 5v8l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v8',
  scissors: 'M6 6l12 12 M6 18L18 6 M7 6a2 2 0 11-2 2 M7 18a2 2 0 10-2-2',
  bulb: 'M9 18h6 M10 21h4 M8 14a6 6 0 118 0c-1 1-1 1.5-1 3H9c0-1.5 0-2-1-3z',
  spark: 'M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z',
  home: 'M3 11l9-8 9 8 M5 10v11h14V10',
  doc: 'M6 3h8l4 4v14H6z M14 3v4h4 M9 13h6 M9 17h6',
  check: 'M5 12l4 4 10-11',
  trash: 'M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13',
  bot: 'M12 3v3 M7 8h10a2 2 0 012 2v7a2 2 0 01-2 2H7a2 2 0 01-2-2v-7a2 2 0 012-2z M9 13h.01 M15 13h.01',
  box: 'M4 5h16v14H4z',
};

function icon(name, cls = 'ic') {
  const d = ICONS[name] || '';
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">` +
    d.split(' M').map((seg, i) => `<path d="${i ? 'M' + seg : seg}"/>`).join('') + `</svg>`;
}

// --- разметка-помощники ------------------------------------------------------

const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content; };
const esc = (s) => String(s ?? '').replace(/[<>&"]/g, (c) => ({'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c]));
const money = (v) => `${Math.round(v).toLocaleString('ru-RU').replace(/ /g, ' ')} ₽`;
const plural = (n, a, b, c) => { const x = Math.abs(n) % 100, y = x % 10; if (x > 10 && x < 20) return c; if (y > 1 && y < 5) return b; return y === 1 ? a : c; };
const go = (screen) => { state.screen = screen; render(); };

// --- экран: портфель объектов ------------------------------------------------

function screenList() {
  const box = h(`
    <div class="screen">
      <div class="top">
        <h1>Мои объекты</h1>
        <button class="icon-btn" id="price" aria-label="Прайс">${icon('wallet', 'ic')}</button>
      </div>
      <div class="list" id="list"></div>
      <div class="dock"><button class="btn" id="new">${icon('plus', 'ic')} Новый объект</button></div>
    </div>`);
  const list = box.querySelector('#list');

  if (!state.projects.length) {
    list.append(h(`<div class="center">${icon('folder', 'ic')}
      <h1>Пока пусто</h1><p class="hint">Заведи первый объект — посчитаю раскладку и закупку.</p></div>`));
  }
  for (const p of state.projects) {
    const money_ = p.due > 0 ? `<span class="pill due">${money(p.due)}</span>`
      : p.deal_amount ? `<span class="pill paid">рассчитались</span>` : '';
    const card = h(`
      <button class="tile-row">
        <span class="grow"><span class="title">${esc(p.title)}</span>
          <span class="sub">${p.surfaces} ${plural(p.surfaces, 'поверхность', 'поверхности', 'поверхностей')}</span></span>
        ${money_}${icon('chevron', 'ic chev')}
      </button>`);
    card.querySelector('button').onclick = () => openProject(p.id);
    list.append(card);
  }
  box.querySelector('#new').onclick = () => { state.draft = {step: 'title', title: '', mode: null}; go('create'); };
  box.querySelector('#price').onclick = () => run(async () => { state.price = (await api('/api/me')).price; state.screen = 'price'; });
  return box;
}

const openProject = (id) => run(async () => {
  state.project = await api(`/api/projects/${id}`);
  state.surface = 0;
  state.lastSchemeUrl = null;
  state.screen = state.project.result ? 'canvas' : 'canvas';
});

// --- экран: холст объекта (герой) --------------------------------------------

const PATTERNS = [['Шов в шов', 'straight'], ['Вразбежку', 'brick'], ['Диагональ', 'diagonal'], ['Ёлочка', 'herringbone']];
const GROUTS = [['Белая', 'white', '#f3f1ee'], ['Серая', 'grey', '#9aa0a6'], ['Бежевая', 'beige', '#d8c6a8'], ['Графит', 'graphite', '#454b52'], ['Чёрная', 'black', '#1c1c1c']];
const OFFSETS = [['1/2', '1/2', 0.5], ['1/3', '1/3', 1 / 3], ['1/4', '1/4', 0.25]];

function screenCanvas() {
  const p = state.project;
  const r = p.result;
  if (!r) {
    const box = h(`<div class="screen"><div class="top">
      <button class="icon-btn" id="back">${icon('back')}</button><h1>${esc(p.title)}</h1></div>
      <div class="center">${icon('box')}<h1>Ещё нет поверхностей</h1>
      <p class="hint">Добавь стену или пол — сразу посчитаю раскладку и закупку.</p></div></div>`);
    box.querySelector('#back').onclick = () => loadList();
    return box;
  }
  const t = r.tile;
  const s = r.surfaces[state.surface] || r.surfaces[0];

  const box = h(`
    <div class="screen">
      <div class="top">
        <button class="icon-btn" id="back">${icon('back')}</button>
        <h1>${esc(p.title)}</h1>
        <button class="icon-btn" id="menu" aria-label="Ещё">${icon('doc')}</button>
      </div>

      <div class="scheme-wrap"><img class="scheme" alt="Схема раскладки"></div>
      <div class="tabs" id="tabs"></div>

      <div class="result">
        <div class="big"><span class="n js-num">${r.tiles_grid}</span>
          <span class="u">${plural(r.tiles_grid, 'плитка', 'плитки', 'плиток')} на объект</span></div>
        <div class="meta js-num">${r.area_m2.toFixed(2)} м² · плитка ${t.width_mm.toFixed(0)}×${t.height_mm.toFixed(0)} (${t.lying ? 'лёжа' : 'стоя'})</div>
        <div class="kpis">
          <div class="kpi"><div class="v js-num">${packs(r)}</div><div class="k">упаковок</div></div>
          <div class="kpi"><div class="v js-num">${r.cuts_count}</div><div class="k">резать</div></div>
          <div class="kpi"><div class="v js-num">${r.walls}${r.has_floor ? '+пол' : ''}</div><div class="k">поверхностей</div></div>
        </div>
      </div>

      <div id="savings"></div>

      <button class="btn secondary" id="buy" style="margin-top:12px">${icon('package', 'ic')} Список закупки</button>

      <div class="spec" id="spec"></div>

      <div id="advice"></div>

      <div class="dock" style="display:flex;flex-direction:column;gap:10px">
        <div class="btn-row">
          <button class="btn secondary" id="estimate">${icon('doc', 'ic')} Смета</button>
          <button class="btn secondary" id="act">${icon('check', 'ic')} Акт</button>
        </div>
        <div class="btn-row">
          <button class="btn secondary" id="money">${icon('wallet', 'ic')} Деньги</button>
          <button class="btn secondary" id="add">${icon('plus', 'ic')} Поверхность</button>
        </div>
      </div>
    </div>`);

  // схема — тап открывает крупно + скачать
  const img = box.querySelector('.scheme');
  if (state.lastSchemeUrl) img.src = state.lastSchemeUrl;
  if (state.computing) img.classList.add('computing');
  img.onclick = openViewer;
  loadScheme(img, p.id, state.surface);

  // табы поверхностей
  const tabs = box.querySelector('#tabs');
  r.surfaces.forEach((sf, i) => {
    const b = h(`<button class="tab ${i === state.surface ? 'on' : ''}">${esc(sf.name)}</button>`);
    b.querySelector('button').onclick = () => { state.surface = i; state.lastSchemeUrl = null; render(); };
    tabs.append(b);
  });

  // экономия
  if (r.savings) {
    box.querySelector('#savings').append(h(`<div class="savings">${icon('spark', 'ic')}
      <span>Эконом сберёг <b>${r.savings.tiles} ${plural(r.savings.tiles, 'плитку', 'плитки', 'плиток')}</b>${r.savings.packs ? ` — ${r.savings.packs} ${plural(r.savings.packs, 'упаковку', 'упаковки', 'упаковок')}` : ''}: остатки уходят за угол, а не в мусор.</span></div>`));
  }

  // спека — живой пересчёт
  buildSpec(box.querySelector('#spec'), r);

  // советы
  const adv = box.querySelector('#advice');
  r.advice.forEach((a) => adv.append(h(`<div class="advice">${icon('bulb', 'ic')}<span>${esc(a)}</span></div>`)));

  box.querySelector('#back').onclick = () => loadList();
  box.querySelector('#buy').onclick = () => go('buy');
  box.querySelector('#menu').onclick = () => go('buy');
  box.querySelector('#estimate').onclick = () => openPaper('estimate');
  box.querySelector('#act').onclick = () => openPaper('act');
  box.querySelector('#money').onclick = () => go('money');
  box.querySelector('#add').onclick = () => { tg?.showAlert?.('Добавление поверхности — в следующем шаге.'); };
  void s;
  return box;
}

const packs = (r) => {
  const line = r.purchase.find((m) => m.kind === 'tile' && m.note && /уп/.test(m.note));
  const m = line && line.note.match(/(\d+)\s*уп/);
  return m ? m[1] : '—';
};

const fmtNum = (v) => String(Math.round(v * 100) / 100).replace('.', ',');
const matchOffset = (ratio) => (OFFSETS.find(([, , r]) => Math.abs(r - ratio) < 1e-6) || ['', '1/2'])[1];

function buildSpec(el, r) {
  const t = r.tile;

  blockRow(el, 'grid', 'Раскладка', seg(PATTERNS, r.pattern, (v) => livePatch({pattern: v})));

  if (r.pattern === 'brick') {
    blockRow(el, 'layers', 'Смещение рядов',
      seg(OFFSETS, matchOffset(r.offset_ratio), (v) => livePatch({offset_label: v})));
  }

  blockRow(el, 'ruler', 'Начало ряда',
    seg([['От угла', 'edge'], ['От центра', 'center'], ['Авто', 'auto']], r.start_from,
      (v) => livePatch({start_from: v})));

  // шов — ± и ввод с клавиатуры (мм)
  valueRow(el, 'grid', 'Шов', {
    value: t.joint_mm, fmt: (v) => `${fmtNum(v)} мм`, min: 0.5, max: 10, step: 0.5,
    onSet: (v) => livePatch({joint_mm: v}),
  });

  // запас — ± и ввод с клавиатуры (%)
  valueRow(el, 'package', 'Запас', {
    value: Math.round(r.waste * 100), fmt: (v) => `${Math.round(v)}%`, min: 0, max: 30, step: 1,
    onSet: (v) => livePatch({waste: v / 100}),
  });

  blockRow(el, 'paint', 'Цвет затирки', chips(GROUTS, r.grout, (v) => livePatch({grout: v})));

  blockRow(el, 'droplet', 'Вид затирки',
    seg([['Цементная', 'cement'], ['Эпоксидная', 'epoxy']], r.grout_kind,
      (v) => livePatch({grout_kind: v})));

  inlineRow(el, 'rotate', 'Повернуть плитку',
    `${t.width_mm.toFixed(0)}×${t.height_mm.toFixed(0)} (${t.lying ? 'лёжа' : 'стоя'})`,
    () => livePatch({rotate: true}));

  if (r.can_wrap) toggleRow(el, 'spark', 'Эконом: лента по кругу', r.wrap, () => livePatch({wrap: !r.wrap}));
  toggleRow(el, 'droplet', 'Гидроизоляция', r.waterproofing, () => livePatch({waterproofing: !r.waterproofing}));
}

/** Сегмент-переключатель: [[label, value], …]. */
function seg(opts, current, onPick) {
  const node = h(`<div class="seg">${opts.map(([l, v]) =>
    `<button data-v="${esc(v)}" class="${current === v ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>`).firstElementChild;
  node.querySelectorAll('button').forEach((b) => b.onclick = () => onPick(b.dataset.v));
  return node;
}

/** Чипы с цветным кружком: [[label, value, color?], …]. */
function chips(opts, current, onPick) {
  const node = h(`<div class="chips">${opts.map(([l, v, c]) =>
    `<button class="chip ${current === v ? 'on' : ''}" data-v="${esc(v)}">${c ? `<span class="dot" style="background:${c}"></span>` : ''}${esc(l)}</button>`).join('')}</div>`).firstElementChild;
  node.querySelectorAll('button').forEach((b) => b.onclick = () => onPick(b.dataset.v));
  return node;
}

/** Широкий контрол под подписью (раскладка, затирка). */
function blockRow(el, ic, lab, control) {
  const block = h(`<div class="spec-block"><div class="spec-lab">${icon(ic, 'ic')}<span>${esc(lab)}</span></div><div class="spec-ctl"></div></div>`).firstElementChild;
  block.querySelector('.spec-ctl').append(control);
  el.append(block);
}

/** Инлайн-строка: подпись слева, кнопка-значение справа. */
function inlineRow(el, ic, lab, valText, onClick) {
  const node = h(`<div class="spec-row">${icon(ic, 'ic')}<span class="lab">${esc(lab)}</span><button class="chip">${esc(valText)}</button></div>`).firstElementChild;
  node.querySelector('.chip').onclick = onClick;
  el.append(node);
}

/** Тумблер. */
function toggleRow(el, ic, lab, on, onClick) {
  const node = h(`<div class="spec-row">${icon(ic, 'ic')}<span class="lab">${esc(lab)}</span><button class="toggle ${on ? 'on' : ''}"></button></div>`).firstElementChild;
  node.querySelector('.toggle').onclick = onClick;
  el.append(node);
}

/** Значение с ± И вводом с клавиатуры (тап по числу). */
function valueRow(el, ic, lab, {value, fmt, min, max, step, onSet}) {
  const clamp = (v) => Math.min(max, Math.max(min, Math.round(v * 100) / 100));
  const node = h(`<div class="spec-row">${icon(ic, 'ic')}<span class="lab">${esc(lab)}</span>
    <span class="stepper"><button class="minus" aria-label="меньше">−</button>
    <button class="cur js-num" aria-label="ввести число">${fmt(value)}</button>
    <button class="plus" aria-label="больше">+</button></span></div>`).firstElementChild;
  node.querySelector('.minus').onclick = () => onSet(clamp(value - step));
  node.querySelector('.plus').onclick = () => onSet(clamp(value + step));
  // тап по числу → поле ввода с клавиатуры
  const cur = node.querySelector('.cur');
  cur.onclick = () => {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.inputMode = 'decimal'; inp.className = 'cur-input';
    inp.value = String(value).replace('.', ',');
    cur.replaceWith(inp); inp.focus(); inp.select();
    let done = false;
    const commit = () => {
      if (done) return; done = true;
      const v = parseFloat(inp.value.replace(',', '.'));
      if (isFinite(v)) onSet(clamp(v)); else render();
    };
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); });
  };
  el.append(node);
}

/** Схему — крупно на весь экран, с попыткой скачать. */
function openViewer() {
  if (!state.lastSchemeUrl) return;
  const surf = state.project.result.surfaces[state.surface];
  const name = `${state.project.title} ${surf?.name || 'схема'}`.replace(/[^\wа-яё \-]/gi, '').trim() + '.png';
  const v = h(`<div class="viewer"><img src="${state.lastSchemeUrl}" alt="Схема раскладки">
    <div class="vbtns"><button class="dl">${icon('resize', 'ic')} Скачать</button>
    <button class="close">Закрыть</button></div></div>`).firstElementChild;
  const close = () => v.remove();
  v.querySelector('.close').onclick = close;
  v.addEventListener('click', (e) => { if (e.target === v) close(); });
  v.querySelector('.dl').onclick = () => {
    // Схема защищена initData, поэтому качаем уже загруженный blob, а не URL
    // (tg.downloadFile сходил бы за ссылкой без подписи и получил 401).
    const a = document.createElement('a');
    a.href = state.lastSchemeUrl; a.download = name;
    document.body.append(a); a.click(); a.remove();
    tg?.HapticFeedback?.impactOccurred('light');
  };
  document.body.append(v);
}

/** Схема — картинкой с сервера (за проверкой initData, тянем blob'ом). */
async function loadScheme(img, projectId, index) {
  try {
    const res = await fetch(`/api/projects/${projectId}/scheme/${index}.png`, {headers: {'X-Init-Data': tg?.initData || ''}});
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    state.lastSchemeUrl = url;
    img.src = url;
    img.classList.remove('computing');
  } catch (e) { console.error(e); }
}

// --- экран: закупка ----------------------------------------------------------

function screenBuy() {
  const r = state.project.result;
  const box = h(`<div class="screen"><div class="top">
    <button class="icon-btn" id="back">${icon('back')}</button><h1>Список закупки</h1></div>
    <div class="card buy" id="lines"></div>
    ${r.tile_cost ? `<p class="hint" style="margin-top:10px">Плитка на ${money(r.tile_cost)}</p>` : ''}</div>`);
  const lines = box.querySelector('#lines');
  r.purchase.forEach((m) => lines.append(h(`<div class="line"><div class="grow"><div>${esc(m.name)}</div>${m.note ? `<div class="note">${esc(m.note)}</div>` : ''}</div><div class="q num">${esc(m.qty_text)} ${esc(m.unit)}</div></div>`)));
  box.querySelector('#back').onclick = () => go('canvas');
  return box;
}

// --- экран: смета / акт -------------------------------------------------------

const openPaper = (kind) => run(async () => { state.paper = await api(`/api/projects/${state.project.id}/${kind}`); state.paper.kind = kind; state.screen = 'paper'; });

function screenPaper() {
  const e = state.paper;
  const isAct = e.kind === 'act';
  const box = h(`<div class="screen"><div class="top">
    <button class="icon-btn" id="back">${icon('back')}</button><h1>${isAct ? 'Акт' : 'Смета'}</h1></div>
    <h2>Работы</h2><div class="card doc" id="works"></div>
    <div class="doc"><div class="total"><span>РАБОТА</span><span class="num">${esc(e.works_total_text)}</span></div></div>
    <h2>${isAct ? 'Материалы' : 'Материалы — купить'}</h2><div class="card doc" id="mats"></div>
    <div class="doc"><div class="total"><span>${isAct ? 'ИТОГО К ОПЛАТЕ' : 'ВСЁ ВМЕСТЕ ≈'}</span><span class="num">${esc(isAct ? e.grand_total_text : e.rough_total_text)}</span></div></div>
    ${isAct ? '' : `<p class="hint" style="margin-top:12px">Материалы заказчик покупает сам, в стоимость работы не входят. Цены примерные, для ориентира.</p>`}
    ${e.note ? `<p class="hint">${esc(e.note)}</p>` : ''}</div>`);
  const works = box.querySelector('#works');
  e.works.forEach((w) => works.append(h(`<div class="line"><div class="grow"><div>${esc(w.name)}</div><div class="qty">${w.qty}${w.unit ? ' ' + esc(w.unit) + ' × ' + money(w.price) : ''}</div></div><div class="q num">${esc(w.total_text)}</div></div>`)));
  const mats = box.querySelector('#mats');
  e.materials.forEach((m) => mats.append(h(`<div class="line"><div class="grow"><div>${esc(m.name)}</div><div class="qty">${esc(m.qty_text)} ${esc(m.unit)}${m.packs ? ` (${m.packs} уп.)` : ''}</div></div><div class="q num muted">${m.cost ? '≈ ' + money(m.cost) : ''}</div></div>`)));
  box.querySelector('#back').onclick = () => go('canvas');
  return box;
}

// --- экран: деньги -----------------------------------------------------------

function screenMoney() {
  const p = state.project;
  const box = h(`<div class="screen"><div class="top">
    <button class="icon-btn" id="back">${icon('back')}</button><h1>Деньги</h1></div>
    <div class="card">
      <div class="line"><span>Договорились</span><b class="num">${money(p.deal_amount)}</b></div>
      <div class="line"><span>Получено</span><b class="num">${money(p.paid)}</b></div>
      <div class="line"><span>Остаток</span><b class="num ${p.due > 0 ? '' : ''}" style="color:${p.due > 0 ? 'var(--danger)' : 'var(--ok)'}">${money(p.due)}</b></div>
    </div>
    <label class="field"><span class="lab">Сумма договора, ₽</span><input type="number" inputmode="decimal" id="deal" value="${p.deal_amount || ''}"></label>
    <button class="btn secondary" id="save-deal" style="margin-top:10px">Записать договор</button>
    <label class="field"><span class="lab">Получил от заказчика, ₽</span></label>
    <div class="two"><input type="number" inputmode="decimal" id="pay" placeholder="30000"><input type="text" id="comment" placeholder="аванс"></div>
    <button class="btn" id="add-pay" style="margin-top:10px">Записать приход</button>
    ${p.payments.length ? '<h2>Приходы</h2>' : ''}<div class="card doc" id="pays" ${p.payments.length ? '' : 'style="display:none"'}></div>
    </div>`);
  const pays = box.querySelector('#pays');
  p.payments.forEach((x) => pays.append(h(`<div class="line"><div class="grow"><div>${esc(x.comment || 'платёж')}</div><div class="qty">${esc(x.at.slice(0, 10))}</div></div><div class="q num">${money(x.amount)}</div></div>`)));
  box.querySelector('#save-deal').onclick = () => run(async () => { const a = parseFloat(box.querySelector('#deal').value || '0'); Object.assign(state.project, await api(`/api/projects/${p.id}/deal`, {method: 'PUT', body: {amount: a}})); });
  box.querySelector('#add-pay').onclick = () => run(async () => { const a = parseFloat(box.querySelector('#pay').value || '0'); if (!(a > 0)) throw new Error('Сумма прихода — больше нуля.'); Object.assign(state.project, await api(`/api/projects/${p.id}/payments`, {method: 'POST', body: {amount: a, comment: box.querySelector('#comment').value}})); });
  box.querySelector('#back').onclick = () => go('canvas');
  return box;
}

// --- экран: прайс ------------------------------------------------------------

const PRICE_FIELDS = [['wall_tiling', 'Укладка на стену, ₽/м²'], ['floor_tiling', 'Укладка на пол, ₽/м²'], ['cutting', 'Подрезка, ₽/шт'], ['grouting', 'Затирка цементной, ₽/м²'], ['grouting_epoxy', 'Затирка эпоксидной, ₽/м²'], ['waterproofing', 'Гидроизоляция, ₽/м²'], ['priming', 'Грунтовка, ₽/м²'], ['demolition', 'Демонтаж, ₽/м²'], ['min_order', 'Мин. чек, ₽']];

function screenPrice() {
  const box = h(`<div class="screen"><div class="top"><button class="icon-btn" id="back">${icon('back')}</button><h1>Прайс</h1></div>
    <p class="hint">Твои расценки — по ним считается смета.</p><div id="f"></div>
    <div class="dock"><button class="btn" id="save">Сохранить</button></div></div>`);
  const f = box.querySelector('#f');
  PRICE_FIELDS.forEach(([k, l]) => f.append(h(`<label class="field"><span class="lab">${l}</span><input type="number" inputmode="decimal" data-k="${k}" value="${state.price[k]}"></label>`)));
  box.querySelector('#save').onclick = () => run(async () => { const body = {}; box.querySelectorAll('input[data-k]').forEach((i) => body[i.dataset.k] = parseFloat(i.value || '0')); state.price = await api('/api/price', {method: 'PUT', body}); tg?.HapticFeedback?.notificationOccurred('success'); state.screen = 'list'; state.projects = await api('/api/projects'); });
  box.querySelector('#back').onclick = () => loadList();
  return box;
}

// --- экран: быстрый ввод -----------------------------------------------------

function screenCreate() {
  const d = state.draft;
  const steps = {
    title: () => ask('Название объекта', 'Ванная, Борзова', 'text', (v) => { if (!v.trim()) throw new Error('Напиши название.'); d.title = v.trim(); d.step = 'mode'; }),
    mode: () => choose('Что считаем?', [['Комната целиком', () => { d.mode = 'room'; d.step = 'walls'; }], ['Одна поверхность', () => { d.mode = 'single'; d.step = 'kind'; }]]),
    walls: () => ask('Стены по кругу, м', '2 1.8 2 1.8', 'text', async (v) => { d.walls = (await measure('walls', v)).values; d.step = 'height'; }, 'по часовой, через пробел — как мерил'),
    height: () => ask('Высота, м', '2.7', 'text', async (v) => { d.height = (await measure('height', v)).values[0]; d.step = d.walls.length === 4 ? 'floor' : 'tile'; if (d.step === 'tile') d.with_floor = false; }),
    floor: () => choose('Пол тоже плиткой?', [['Да, и пол', () => { d.with_floor = true; d.step = 'tile'; }], ['Только стены', () => { d.with_floor = false; d.step = 'tile'; }]]),
    kind: () => choose('Что меряем?', [['Стена', () => { d.kind = 'wall'; d.step = 'size'; }], ['Пол', () => { d.kind = 'floor'; d.step = 'size'; }]]),
    size: () => ask('Ширина и высота, м', '2 2.7', 'text', async (v) => { const [w, hh] = (await measure('size', v)).values; d.width_m = w; d.height_m = hh; d.step = 'tile'; }),
    tile: () => ask('Плитка, см', '60 30', 'text', async (v) => { const [w, hh] = (await measure('tile', v)).values; d.tile = {width_mm: w, height_mm: hh, joint_mm: 2, thickness_mm: 9}; d.pattern = 'straight'; d.start_from = 'auto'; d.waste = 0.07; await save(); }, 'можно в см (60 30) или мм (600 300). Шов, раскладку и запас докрутишь на холсте.'),
  };
  // Без своего run(): save() зовётся ИЗ ask() (внутри run()), вложенный run()
  // увидел бы busy и молча вышел — объект бы не создался, а поле «сбросилось».
  async function save() {
    const pr = await api('/api/projects', {method: 'POST', body: {title: d.title}});
    const common = {tile: d.tile, pattern: d.pattern, start_from: d.start_from, waste: d.waste, waterproofing: false};
    if (d.mode === 'room') await api(`/api/projects/${pr.id}/room`, {method: 'POST', body: {...common, walls_m: d.walls, height_m: d.height, with_floor: !!d.with_floor}});
    else await api(`/api/projects/${pr.id}/surface`, {method: 'POST', body: {...common, kind: d.kind, width_m: d.width_m, height_m: d.height_m}});
    state.draft = null; state.project = await api(`/api/projects/${pr.id}`); state.surface = 0; state.lastSchemeUrl = null; state.screen = 'canvas';
  }
  return steps[d.step]();
}

function ask(title, ph, type, onNext, hint = '') {
  const box = h(`<div class="screen"><div class="top"><button class="icon-btn" id="back">${icon('back')}</button><h1>${esc(title)}</h1></div>
    ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}
    <input type="${type === 'number' ? 'number' : 'text'}" inputmode="${type === 'number' ? 'numeric' : 'text'}" placeholder="${esc(ph)}" style="margin-top:10px">
    <div class="dock"><button class="btn" id="next">Дальше</button></div></div>`);
  const input = box.querySelector('input');
  const submit = () => run(async () => { await onNext(input.value); });
  box.querySelector('#next').onclick = submit;
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  setTimeout(() => input.focus(), 40);
  box.querySelector('#back').onclick = () => { state.draft = null; loadList(); };
  return box;
}

function choose(title, opts) {
  const box = h(`<div class="screen"><div class="top"><button class="icon-btn" id="back">${icon('back')}</button><h1>${esc(title)}</h1></div><div class="list" id="o"></div></div>`);
  const o = box.querySelector('#o');
  opts.forEach(([l, fn]) => { const b = h(`<button class="btn secondary">${esc(l)}</button>`); b.querySelector('button').onclick = () => run(async () => { await fn(); }); o.append(b); });
  box.querySelector('#back').onclick = () => { state.draft = null; loadList(); };
  return box;
}

// --- сборка ------------------------------------------------------------------

const loadList = () => run(async () => { state.projects = await api('/api/projects'); state.project = null; state.screen = 'list'; });

function skeletonList() {
  return h(`<div class="screen"><div class="top"><h1>Мои объекты</h1></div>
    <div class="skel skel-card"></div><div class="skel skel-card"></div><div class="skel skel-card"></div></div>`);
}

function render() {
  const screens = {
    list: screenList, create: screenCreate, canvas: screenCanvas,
    buy: screenBuy, paper: screenPaper, money: screenMoney, price: screenPrice,
    loading: skeletonList,
  };
  root.replaceChildren((screens[state.screen] || screenList)());
  if (tg?.BackButton) { if (state.screen === 'list') tg.BackButton.hide(); else tg.BackButton.show(); }
}

tg?.ready();
tg?.expand();
tg?.BackButton?.onClick(() => {
  const s = state.screen;
  if (s === 'list') return;
  if (s === 'canvas' || s === 'price') loadList();
  else if (s === 'create') { state.draft = null; loadList(); }
  else go('canvas');
});

// Открыт вне Telegram (ссылка в браузере) — initData пуст, сервер ответит 401.
if (!tg || !tg.initData) {
  root.replaceChildren(h(`<div class="screen"><div class="center">${icon('bot')}
    <h1>Откройте через бота</h1>
    <p class="hint">Приложение работает внутри Telegram. Откройте чат с ботом и нажмите кнопку
    <b>«Приложение»</b> слева от поля ввода — там Telegram передаёт, кто вы.</p>
    <p class="hint">Ссылку в обычном браузере открывать не нужно: там нет вашей учётки.</p></div></div>`));
} else {
  state.screen = 'loading';
  render();
  loadList();
}
