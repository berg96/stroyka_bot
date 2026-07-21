/* Мини-апп плиточника v2 — «объект-холст».
 *
 * Центр приложения — не опросник, а экран объекта: схема-герой сверху, под ней
 * живая спека, где любой параметр правится на месте с мгновенным пересчётом.
 * Ввод сжат в один быстрый экран. Числа считает бэкенд (одно ядро с ботом) — тут
 * ни одной формулы, только показ и PATCH.
 */

const tg = window.Telegram?.WebApp;
const root = document.getElementById('app');

// Штамп сборки. Зашит в САМ app.js, поэтому показывает, какой JS реально загружен
// (а не какой отдаёт сервер). Старый штамп на экране = WebView держит старый файл
// из кэша. Меняй строку при каждом деплое фронта.
const BUILD = '21.07 · 12:30 · переключатели-fix';

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
  // Структурные смены меняют НАБОР контролов спеки (раскладка добавляет «смещение»;
  // поворот/размер меняют подписи) → перерисовываем. Остальное (шов/запас/старт/
  // затирка/эконом/гидро) — точечно, без перезагрузки страницы.
  const structural = 'pattern' in body || 'rotate' in body || 'tile_size' in body;
  try {
    const result = await api(`/api/projects/${state.project.id}`, {method: 'PATCH', body});
    if (v !== patchVersion) return; // пришёл ответ на устаревший параметр — игнор
    state.project.result = result;
    setComputing(false);
    tg?.HapticFeedback?.notificationOccurred('success');
    if (structural || state.screen !== 'canvas' || !document.querySelector('#c-tiles')) {
      render();
    } else {
      paintCanvasResult(result);
      loadScheme(document.querySelector('.scheme'), state.project.id, state.surface);
    }
  } catch (e) {
    if (v !== patchVersion) return;
    setComputing(false);
    fail(e);
  }
}

function paintCanvasResult(r) {
  const set = (id, val) => { const e = document.querySelector(id); if (e) e.textContent = val; };
  const t = r.tile;
  set('#c-tiles', r.tiles_grid);
  set('#c-meta', `${r.area_m2.toFixed(2)} м² · плитка ${t.width_mm.toFixed(0)}×${t.height_mm.toFixed(0)} (${t.lying ? 'лёжа' : 'стоя'})`);
  set('#c-packs', packs(r));
  set('#c-cuts', r.cuts_count);
  const sv = document.querySelector('#savings');
  if (sv) {
    sv.innerHTML = '';
    if (r.savings) sv.append(h(`<div class="savings">${icon('spark', 'ic')}<span>Эконом сберёг <b>${r.savings.tiles} ${plural(r.savings.tiles, 'плитку', 'плитки', 'плиток')}</b>${r.savings.packs ? ` — ${r.savings.packs} ${plural(r.savings.packs, 'упаковку', 'упаковки', 'упаковок')}` : ''}: остатки уходят за угол, а не в мусор.</span></div>`));
  }
  const ad = document.querySelector('#advice');
  if (ad) { ad.innerHTML = ''; r.advice.forEach((a) => ad.append(h(`<div class="advice">${icon('bulb', 'ic')}<span>${esc(a)}</span></div>`))); }
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
    card.querySelector('button').onclick = () => openObject(p.id);
    list.append(card);
  }
  box.querySelector('#new').onclick = () => { state.draft = {step: 'title', title: '', mode: null}; go('create'); };
  box.querySelector('#price').onclick = () => run(async () => { state.price = (await api('/api/me')).price; state.screen = 'price'; });
  box.append(h(`<div class="build-tag">${esc(BUILD)}</div>`));
  return box;
}

/** Объект = замеры + список работ (плитка + другие виды). */
const openObject = (id) => run(async () => {
  state.object = await api(`/api/objects/${id}`);
  state.screen = 'object';
});

const reloadObject = async () => { state.object = await api(`/api/objects/${state.object.id}`); };

/** Плитка — одна из работ; открываем её богатый холст (существующий экран). */
const openTile = () => run(async () => {
  state.project = await api(`/api/projects/${state.object.id}`);
  state.surface = 0;
  state.lastSchemeUrl = null;
  state.screen = state.project.result ? 'canvas' : 'canvas';
});

const backToObject = () => (state.object ? go('object') : loadList());

// --- экран: объект с работами (хаб 4.1) --------------------------------------

const WORK_TYPES = [
  ['tile', 'Плитка', 'grid', 'схема, рез, закупка'],
  ['plaster', 'Штукатурка', 'box', 'площадь + смесь'],
  ['laminate', 'Ламинат', 'layers', 'пачки + подложка'],
  ['baseboard', 'Плинтус', 'ruler', 'планки + уголки'],
  ['reveals', 'Откосы', 'door', 'по проёмам'],
  ['plumbing', 'Сантехника', 'droplet', 'список точек'],
];
const WORK_ICON = Object.fromEntries(WORK_TYPES.map(([k, , i]) => [k, i]));

function screenObject() {
  const o = state.object;
  const m = o.measures || {};
  const mSum = m.walls && m.walls.length
    ? `стены ${m.walls.map(fmtNum).join('·')} · h ${fmtNum(m.height_m || 0)}${m.floor_m2 ? ` · пол ${fmtNum(m.floor_m2)} м²` : ''}`
    : 'замеры не заданы';
  const box = h(`<div class="screen">
    <div class="top"><button class="icon-btn" id="back">${icon('back')}</button>
      <h1 id="title" title="Переименовать">${esc(o.title)}</h1></div>
    <div class="card"><div class="row"><span class="muted">Замеры комнаты</span>
      <span class="hint">переиспользуются</span></div>
      <div class="hint" style="margin-top:6px">${esc(mSum)}</div></div>
    <h2>Работы</h2>
    <div class="list" id="works"></div>
    <button class="btn secondary" id="addwork" style="margin-top:10px">${icon('plus', 'ic')} Добавить работу</button>
    <div class="dock" style="display:flex;flex-direction:column;gap:10px">
      <button class="btn" id="estimate">${icon('doc', 'ic')} Смета${o.total ? ' · ' + money(o.total) : ''}</button>
      <div class="btn-row">
        <button class="btn secondary" id="act">${icon('check', 'ic')} Акт</button>
        <button class="btn secondary" id="money">${icon('wallet', 'ic')} Деньги</button>
        <button class="btn secondary" id="price">Прайс</button>
      </div>
    </div></div>`);
  const works = box.querySelector('#works');
  if (!o.works.length) {
    works.append(h(`<div class="hint" style="padding:4px 2px">Добавь первую работу — плитка, штукатурка, ламинат, сантехника… соберём всё в одну смету.</div>`));
  }
  o.works.forEach((w) => {
    const card = h(`<button class="tile-row">${icon(WORK_ICON[w.kind] || 'box', 'ic')}
      <span class="grow"><span class="title">${esc(w.name)}</span>
        <span class="sub">${esc(w.hero_value)}${w.hero_note ? ' · ' + esc(w.hero_note) : ''}</span></span>
      <span class="pill">${money(w.work_sum)}</span>${icon('chevron', 'ic chev')}</button>`);
    card.querySelector('button').onclick = () => (w.kind === 'tile' ? openTile() : openWork(w));
    works.append(card);
  });
  const titleEl = box.querySelector('#title');
  titleEl.onclick = () => editTitle(titleEl, o);
  box.querySelector('#back').onclick = () => loadList();
  box.querySelector('#addwork').onclick = () => go('addwork');
  box.querySelector('#estimate').onclick = () => openObjectPaper('estimate');
  box.querySelector('#act').onclick = () => openObjectPaper('act');
  box.querySelector('#money').onclick = () => run(async () => { state.project = await api(`/api/projects/${o.id}`); state.screen = 'money'; });
  box.querySelector('#price').onclick = () => run(async () => { state.price = (await api('/api/me')).price; state.screen = 'price'; });
  return box;
}

/** Общая смета/акт по объекту — все работы в один документ (экран screenPaper). */
const openObjectPaper = (kind) => run(async () => {
  state.paper = await api(`/api/objects/${state.object.id}/${kind}`);
  state.paper.kind = kind;
  state.paper.fromObject = true;
  state.screen = 'paper';
});

// --- экран: добавить работу (4.2) --------------------------------------------

function screenAddWork() {
  const o = state.object;
  const has = new Set(o.works.map((w) => w.kind));
  const box = h(`<div class="screen">
    <div class="top"><button class="icon-btn" id="back">${icon('back')}</button><h1>Какая работа?</h1></div>
    <div class="list" id="types"></div></div>`);
  const types = box.querySelector('#types');
  WORK_TYPES.forEach(([kind, name, ic, sub]) => {
    const exists = kind === 'tile' && has.has('tile');
    const card = h(`<button class="tile-row">${icon(ic, 'ic-lg ic')}
      <span class="grow"><span class="title">${esc(name)}</span>
        <span class="sub">${esc(exists ? 'уже добавлена — открыть' : sub)}</span></span>
      ${icon('chevron', 'ic chev')}</button>`);
    card.querySelector('button').onclick = () => {
      if (kind === 'tile') { has.has('tile') ? openTile() : tg?.showAlert?.('Плитка добавляется при создании объекта (замеры комнаты).'); return; }
      addWork(kind);
    };
    types.append(card);
  });
  box.querySelector('#back').onclick = () => go('object');
  return box;
}

const addWork = (kind) => run(async () => {
  state.work = await api(`/api/objects/${state.object.id}/works`, {method: 'POST', body: {kind}});
  await reloadObject();
  state.screen = 'work';
});

const openWork = (w) => run(async () => {
  state.work = await api(`/api/objects/${state.object.id}/works/${w.id}`);
  state.screen = 'work';
});

// --- экран: вид работ (герой 4.3) --------------------------------------------

let wTimer = null;
let wVer = 0;
let wPending = {};

function workPatch(input) {
  Object.assign(wPending, input);
  tg?.HapticFeedback?.impactOccurred('light');
  root.querySelectorAll('.js-wnum').forEach((n) => n.classList.add('computing-dim'));
  clearTimeout(wTimer);
  wTimer = setTimeout(fireWorkPatch, 120);
}

async function fireWorkPatch() {
  const input = wPending; wPending = {};
  const v = ++wVer;
  try {
    const w = await api(`/api/objects/${state.object.id}/works/${state.work.id}`, {method: 'PATCH', body: {input}});
    if (v !== wVer) return;
    state.work = w;
    tg?.HapticFeedback?.notificationOccurred('success');
    // Точечно, БЕЗ перерисовки всей страницы: обновляем только результат и строки.
    // Панель ввода (степперы/чипы) держит своё состояние сама.
    const hero = document.querySelector('#w-hero');
    if (state.screen === 'work' && hero) {
      hero.textContent = money(w.work_sum);
      document.querySelector('#w-meta').textContent = `${w.hero_value}${w.hero_note ? ' · ' + w.hero_note : ''}`;
      paintWorkLines(document.querySelector('#lines'), w);
      root.querySelectorAll('.js-wnum').forEach((n) => n.classList.remove('computing-dim'));
    } else {
      render();
    }
  } catch (e) { if (v !== wVer) return; fail(e); }
}

function paintWorkLines(el, w) {
  el.innerHTML = '';
  w.work_lines.forEach((ln) => el.append(h(`<div class="line"><div class="grow">${esc(ln.name)}</div><div class="q num js-wnum">${esc(ln.total_text)}</div></div>`)));
  w.materials.forEach((m) => el.append(h(`<div class="line"><div class="grow"><div>${esc(m.name)}</div>${m.note ? `<div class="note">${esc(m.note)}</div>` : ''}</div><div class="q num">${esc(m.qty_text)} ${esc(m.unit)}</div></div>`)));
}

function screenWork() {
  const o = state.object;
  const w = state.work;
  const box = h(`<div class="screen">
    <div class="top"><button class="icon-btn" id="back">${icon('back')}</button>
      <h1>${esc(w.name)}</h1>
      <button class="icon-btn" id="del" aria-label="Удалить">${icon('trash')}</button></div>
    <p class="hint">${esc(o.title)} · из замеров комнаты</p>
    <div class="tabs" id="tabs"></div>
    <h2>Ввод · правится на месте</h2>
    <div class="spec" id="input"></div>
    <div class="result" style="margin-top:16px">
      <div class="big"><span class="n js-wnum" id="w-hero">${money(w.work_sum)}</span><span class="u">работа</span></div>
      <div class="meta js-wnum" id="w-meta">${esc(w.hero_value)}${w.hero_note ? ' · ' + esc(w.hero_note) : ''}</div>
    </div>
    <h2>В смету пойдёт</h2>
    <div class="card buy" id="lines"></div>
    <div class="dock"><button class="btn" id="save">Готово</button></div></div>`);

  // табы всех работ объекта
  const tabs = box.querySelector('#tabs');
  o.works.forEach((ow) => {
    const b = h(`<button class="tab ${ow.id === w.id ? 'on' : ''}">${esc(ow.name)}</button>`);
    b.querySelector('button').onclick = () => (ow.id === w.id ? null : ow.kind === 'tile' ? openTile() : openWork(ow));
    tabs.append(b);
  });

  workInput(box.querySelector('#input'), w);
  paintWorkLines(box.querySelector('#lines'), w);

  box.querySelector('#back').onclick = () => run(async () => { await reloadObject(); state.screen = 'object'; });
  box.querySelector('#save').onclick = () => run(async () => { await reloadObject(); state.screen = 'object'; });
  box.querySelector('#del').onclick = () => {
    const ok = () => run(async () => { await api(`/api/objects/${o.id}/works/${w.id}`, {method: 'DELETE'}); await reloadObject(); state.screen = 'object'; });
    if (tg?.showConfirm) tg.showConfirm(`Удалить работу «${w.name}»?`, (yes) => yes && ok());
    else if (confirm(`Удалить «${w.name}»?`)) ok();
  };
  return box;
}

/** Панель ввода вида работ — контролы шлют workPatch, результат пересчитывается. */
function workInput(el, w) {
  const i = w.input || {};
  const m = state.object.measures || {};
  const perim = (m.walls || []).reduce((a, b) => a + b, 0);
  const wallArea = perim * (m.height_m || 0);
  const floor = m.floor_m2 || 0;
  if (w.kind === 'plaster') {
    // Площадь стен из замеров, но правится (потолок/часть стены/своё число).
    valueRow(el, 'box', 'Площадь', {value: i.area_m2 ?? Math.round(wallArea * 100) / 100, fmt: (v) => `${fmtNum(v)} м²`, min: 0, max: 500, step: 0.5, onSet: (v) => workPatch({area_m2: v})});
    valueRow(el, 'box', 'Слои', {value: i.layers ?? 1, fmt: (v) => String(Math.round(v)), min: 1, max: 3, step: 1, onSet: (v) => workPatch({layers: Math.round(v)})});
    valueRow(el, 'droplet', 'Расход смеси', {value: i.kg_per_m2 ?? 1.2, fmt: (v) => `${fmtNum(v)} кг/м²`, min: 0.5, max: 15, step: 0.5, onSet: (v) => workPatch({kg_per_m2: v})});
    // Потолок штукатурят не всегда → галочка; площадь потолка бот берёт из замеров (≈ пол).
    toggleRow(el, 'box', 'Считать потолок', !!i.with_ceiling, (v) => workPatch({with_ceiling: v}));
  } else if (w.kind === 'laminate') {
    // Площадь пола из замеров — если её нет (комната без пола), мастер вводит сам.
    valueRow(el, 'box', 'Пол', {value: i.area_m2 ?? Math.round(floor * 100) / 100, fmt: (v) => `${fmtNum(v)} м²`, min: 0, max: 500, step: 0.1, onSet: (v) => workPatch({area_m2: v})});
    valueRow(el, 'box', 'Пачка', {value: i.pack_m2 ?? 2.1, fmt: (v) => `${fmtNum(v)} м²`, min: 0.5, max: 5, step: 0.1, onSet: (v) => workPatch({pack_m2: v})});
    blockRow(el, 'layers', 'Схема укладки', seg([['Прямая', '0.05'], ['Диагональ', '0.12'], ['Ёлочка', '0.15']], String(i.waste ?? 0.05), (v) => workPatch({waste: parseFloat(v)})));
    toggleRow(el, 'grid', 'Подложка', i.underlay !== false, (v) => workPatch({underlay: v}));
  } else if (w.kind === 'baseboard') {
    // Периметр и углы предполагаются из замеров (N стен → N внутр. углов),
    // соединители считаются авто (планок−1). Всё правится.
    const nWalls = (m.walls || []).length || 4;
    valueRow(el, 'ruler', 'Периметр', {value: i.perimeter_m ?? Math.round(perim * 100) / 100, fmt: (v) => `${fmtNum(v)} м`, min: 0, max: 200, step: 0.1, onSet: (v) => workPatch({perimeter_m: v})});
    valueRow(el, 'ruler', 'Длина планки', {value: i.plank_m ?? 2.5, fmt: (v) => `${fmtNum(v)} м`, min: 1, max: 4, step: 0.1, onSet: (v) => workPatch({plank_m: v})});
    valueRow(el, 'grid', 'Внутр. углов', {value: i.inner_corners ?? nWalls, fmt: (v) => String(Math.round(v)), min: 0, max: 20, step: 1, onSet: (v) => workPatch({inner_corners: Math.round(v)})});
    valueRow(el, 'grid', 'Внешних углов', {value: i.outer_corners ?? 0, fmt: (v) => String(Math.round(v)), min: 0, max: 20, step: 1, onSet: (v) => workPatch({outer_corners: Math.round(v)})});
    valueRow(el, 'door', 'Заглушек', {value: i.end_caps ?? 0, fmt: (v) => String(Math.round(v)), min: 0, max: 20, step: 1, onSet: (v) => workPatch({end_caps: Math.round(v)})});
  } else if (w.kind === 'reveals') {
    valueRow(el, 'ruler', 'Ширина откоса', {value: i.reveal_width_cm ?? 25, fmt: (v) => `${fmtNum(v)} см`, min: 5, max: 60, step: 1, onSet: (v) => workPatch({reveal_width_cm: v})});
    revealsOpenings(el, i.openings || []);
  } else if (w.kind === 'plumbing') {
    plumbingPoints(el, i.points || []);
  }
}

function revealsOpenings(el, openings) {
  let list = openings.slice();
  el.append(h(`<div class="spec-lab" style="margin-top:8px">${icon('door', 'ic')}<span>Проёмы (окна и двери)</span></div>`));
  const listEl = h(`<div id="openings"></div>`).firstElementChild;
  const paint = () => {
    listEl.innerHTML = '';
    list.forEach((o, idx) => {
      const row = h(`<div class="opening-row">
        <input class="op-name" type="text" value="${esc(o.name || 'Проём')}" placeholder="окно">
        <input class="op-w cur-input" inputmode="decimal" value="${o.width_m || ''}" placeholder="ш">
        <span class="op-x">×</span>
        <input class="op-h cur-input" inputmode="decimal" value="${o.height_m || ''}" placeholder="в">
        <span class="hint">м</span>
        <button class="icon-btn op-del" aria-label="убрать">${icon('trash', 'ic-sm ic')}</button></div>`).firstElementChild;
      const num = (sel) => parseFloat(row.querySelector(sel).value.replace(',', '.')) || 0;
      const upd = () => {
        list[idx] = {name: row.querySelector('.op-name').value || 'Проём', width_m: num('.op-w'), height_m: num('.op-h')};
        workPatch({openings: list});
      };
      row.querySelectorAll('input').forEach((inp) => inp.onchange = upd);
      row.querySelector('.op-del').onclick = () => { list = list.filter((_, j) => j !== idx); paint(); workPatch({openings: list}); };
      listEl.append(row);
    });
  };
  paint();
  el.append(listEl);
  const add = h(`<button class="btn secondary" style="margin-top:8px">${icon('plus', 'ic')} Добавить проём</button>`);
  add.querySelector('button').onclick = () => { list = [...list, {name: 'Окно', width_m: 1.2, height_m: 1.4}]; paint(); workPatch({openings: list}); };
  el.append(add);
}

function plumbingPoints(el, points) {
  // Локальная мутабельная копия: точечный workPatch НЕ перерисовывает панель ввода,
  // поэтому контрол держит своё состояние сам (как toggleRow/valueRow). Раньше клик
  // считал next от исходного `points` и не менял вид кнопки — переключатель не
  // загорался, а соседние клики затирали друг друга (слали устаревший набор).
  const list = points.map((p) => ({...p}));
  list.forEach((p) => {
    const row = h(`<div class="spec-row">
      <button class="toggle ${p.on ? 'on' : ''}"></button>
      <span class="lab">${esc(p.name)}</span>
      <input class="cur-input" inputmode="numeric" value="${p.price}" style="width:84px">
    </div>`).firstElementChild;
    const btn = row.querySelector('.toggle');
    btn.onclick = () => {
      p.on = !p.on;
      btn.classList.toggle('on', p.on);  // оптимистично, как toggleRow
      workPatch({points: list});
    };
    row.querySelector('input').onchange = (e) => {
      p.price = parseFloat(e.target.value) || 0;
      workPatch({points: list});
    };
    el.append(row);
  });
}

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
    box.querySelector('#back').onclick = backToObject;
    return box;
  }
  const t = r.tile;
  const s = r.surfaces[state.surface] || r.surfaces[0];

  const box = h(`
    <div class="screen">
      <div class="top">
        <button class="icon-btn" id="back">${icon('back')}</button>
        <h1 id="title" title="Переименовать">${esc(p.title)}</h1>
        <button class="icon-btn" id="menu" aria-label="Ещё">${icon('doc')}</button>
      </div>

      <div class="tabs" id="work-tabs"></div>
      <div class="scheme-wrap"><img class="scheme" alt="Схема раскладки"></div>
      <div class="tabs" id="tabs"></div>

      <div class="result">
        <div class="big"><span class="n js-num" id="c-tiles">${r.tiles_grid}</span>
          <span class="u">${plural(r.tiles_grid, 'плитка', 'плитки', 'плиток')} на объект</span></div>
        <div class="meta js-num" id="c-meta">${r.area_m2.toFixed(2)} м² · плитка ${t.width_mm.toFixed(0)}×${t.height_mm.toFixed(0)} (${t.lying ? 'лёжа' : 'стоя'})</div>
        <div class="kpis">
          <div class="kpi"><div class="v js-num" id="c-packs">${packs(r)}</div><div class="k">упаковок</div></div>
          <div class="kpi"><div class="v js-num" id="c-cuts">${r.cuts_count}</div><div class="k">резать</div></div>
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

  // Табы всех работ объекта — чтобы с плитки уйти на другую работу без хаба.
  const wtabs = box.querySelector('#work-tabs');
  if (state.object && state.object.works && state.object.works.length > 1) {
    state.object.works.forEach((ow) => {
      const b = h(`<button class="tab ${ow.kind === 'tile' ? 'on' : ''}">${esc(ow.name)}</button>`);
      b.querySelector('button').onclick = () => (ow.kind === 'tile' ? null : openWork(ow));
      wtabs.append(b);
    });
  } else {
    wtabs.remove();
  }

  const titleEl = box.querySelector('#title');
  titleEl.onclick = () => editTitle(titleEl, p);
  box.querySelector('#back').onclick = backToObject;
  box.querySelector('#buy').onclick = () => go('buy');
  box.querySelector('#menu').onclick = () => go('buy');
  box.querySelector('#estimate').onclick = () => openPaper('estimate');
  box.querySelector('#act').onclick = () => openPaper('act');
  box.querySelector('#money').onclick = () => go('money');
  box.querySelector('#add').onclick = () => { tg?.showAlert?.('Добавление поверхности — в следующем шаге.'); };
  void s;
  return box;
}

/** Переименование объекта: тап по названию → инпут → PUT. */
function editTitle(el, p) {
  const inp = document.createElement('input');
  inp.type = 'text'; inp.className = 'title-input'; inp.value = p.title; inp.maxLength = 128;
  el.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') inp.blur();
    if (e.key === 'Escape') { done = true; render(); }
  });
  inp.addEventListener('blur', () => run(async () => {
    if (done) return; done = true;
    const t = inp.value.trim();
    if (!t || t === p.title) { render(); return; }
    // p — это текущий объект (state.object на хабе или state.project на холсте):
    // обновляем именно его, а не жёстко state.project (на хабе он может быть пуст).
    Object.assign(p, await api(`/api/projects/${p.id}/title`, {method: 'PUT', body: {title: t}}));
  }));
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

  sizeRow(el, r);

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

  if (r.can_wrap) toggleRow(el, 'spark', 'Эконом: лента по кругу', r.wrap, (v) => livePatch({wrap: v}));
  toggleRow(el, 'droplet', 'Гидроизоляция', r.waterproofing, (v) => livePatch({waterproofing: v}));
}

/** Сегмент-переключатель: [[label, value], …]. */
function seg(opts, current, onPick) {
  const node = h(`<div class="seg">${opts.map(([l, v]) =>
    `<button data-v="${esc(v)}" class="${current === v ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>`).firstElementChild;
  node.querySelectorAll('button').forEach((b) => b.onclick = () => {
    // Оптимистично подсвечиваем выбранный — чтобы не ждать render (его может и не быть).
    node.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    onPick(b.dataset.v);
  });
  return node;
}

/** Чипы с цветным кружком: [[label, value, color?], …]. */
function chips(opts, current, onPick) {
  const node = h(`<div class="chips">${opts.map(([l, v, c]) =>
    `<button class="chip ${current === v ? 'on' : ''}" data-v="${esc(v)}">${c ? `<span class="dot" style="background:${c}"></span>` : ''}${esc(l)}</button>`).join('')}</div>`).firstElementChild;
  node.querySelectorAll('button').forEach((b) => b.onclick = () => {
    node.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    onPick(b.dataset.v);
  });
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
  // Держит своё состояние: точечный patch НЕ перерисовывает панель, поэтому читать
  // исходный проп в колбэке нельзя — второй клик слал бы то же значение (ровно
  // stale-closure баг, что был у переключателей сантехники). Отдаём НОВОЕ значение.
  let cur = on;
  const node = h(`<div class="spec-row">${icon(ic, 'ic')}<span class="lab">${esc(lab)}</span><button class="toggle ${on ? 'on' : ''}"></button></div>`).firstElementChild;
  const t = node.querySelector('.toggle');
  t.onclick = () => { cur = !cur; t.classList.toggle('on', cur); onClick(cur); };
  el.append(node);
}

/** Размер плитки активной поверхности — тап открывает ввод (в см), меняет размер.
 * У стен и пола плитка своя, поэтому патчим по kind активной поверхности. */
function sizeRow(el, r) {
  const s = r.surfaces[state.surface] || r.surfaces[0];
  const kindTxt = r.has_floor ? ` · ${s.kind === 'floor' ? 'пол' : 'стены'}` : '';
  const node = h(`<div class="spec-row">${icon('resize', 'ic')}<span class="lab">Размер плитки${kindTxt}</span>
    <button class="chip">${s.tile_w.toFixed(0)}×${s.tile_h.toFixed(0)}</button></div>`).firstElementChild;
  const chip = node.querySelector('.chip');
  chip.onclick = () => {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.inputMode = 'decimal'; inp.className = 'cur-input'; inp.style.width = '92px';
    inp.value = `${fmtNum(s.tile_w / 10)} ${fmtNum(s.tile_h / 10)}`;
    chip.replaceWith(inp); inp.focus(); inp.select();
    let done = false;
    const commit = async () => {
      if (done) return; done = true;
      try {
        const {values} = await measure('tile', inp.value);
        livePatch({tile_size: {width_mm: values[0], height_mm: values[1], kind: s.kind}});
      } catch (e) { fail(e); }
    };
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); });
  };
  el.append(node);
}

/** Значение с ± И вводом с клавиатуры (тап по числу). */
function valueRow(el, ic, lab, {value, fmt, min, max, step, onSet}) {
  const clamp = (v) => Math.min(max, Math.max(min, Math.round(v * 100) / 100));
  let val = value;
  const node = h(`<div class="spec-row">${icon(ic, 'ic')}<span class="lab">${esc(lab)}</span>
    <span class="stepper"><button class="minus" aria-label="меньше">−</button>
    <span class="cur-slot"></span>
    <button class="plus" aria-label="больше">+</button></span></div>`).firstElementChild;
  const slot = node.querySelector('.cur-slot');
  // Контрол обновляет СВОЙ дисплей сам (без render всей страницы), onSet шлёт патч.
  const paint = () => { slot.innerHTML = `<button class="cur js-num" aria-label="ввести число">${fmt(val)}</button>`; slot.querySelector('.cur').onclick = edit; };
  const set = (v) => { val = clamp(v); paint(); onSet(val); };
  function edit() {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.inputMode = 'decimal'; inp.className = 'cur-input';
    inp.value = String(val).replace('.', ',');
    slot.replaceChildren(inp); inp.focus(); inp.select();
    let done = false;
    const commit = () => {
      if (done) return; done = true;
      const v = parseFloat(inp.value.replace(',', '.'));
      if (isFinite(v)) set(clamp(v)); else paint();
    };
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); });
  }
  node.querySelector('.minus').onclick = () => set(val - step);
  node.querySelector('.plus').onclick = () => set(val + step);
  paint();
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
  box.querySelector('#back').onclick = () => (e.fromObject ? go('object') : go('canvas'));
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
  // Ссылки на инпуты берём СЕЙЧАС: box — это DocumentFragment, после render() он
  // вставится в DOM и опустеет, и box.querySelector в клике вернул бы null.
  const dealInp = box.querySelector('#deal');
  const payInp = box.querySelector('#pay');
  const commentInp = box.querySelector('#comment');
  box.querySelector('#save-deal').onclick = () => run(async () => { const a = parseFloat(dealInp.value || '0'); Object.assign(state.project, await api(`/api/projects/${p.id}/deal`, {method: 'PUT', body: {amount: a}})); });
  box.querySelector('#add-pay').onclick = () => run(async () => { const a = parseFloat(payInp.value || '0'); if (!(a > 0)) throw new Error('Сумма прихода — больше нуля.'); Object.assign(state.project, await api(`/api/projects/${p.id}/payments`, {method: 'POST', body: {amount: a, comment: commentInp.value}})); });
  box.querySelector('#back').onclick = () => (state.object ? go('object') : go('canvas'));
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
  // f останется в DOM после render(), из него и читаем инпуты в клике (не из box —
  // тот к моменту клика опустеет, будучи DocumentFragment).
  box.querySelector('#save').onclick = () => run(async () => { const body = {}; f.querySelectorAll('input[data-k]').forEach((i) => body[i.dataset.k] = parseFloat(i.value || '0')); state.price = await api('/api/price', {method: 'PUT', body}); tg?.HapticFeedback?.notificationOccurred('success'); state.screen = 'list'; state.projects = await api('/api/projects'); });
  box.querySelector('#back').onclick = () => loadList();
  return box;
}

// --- экран: быстрый ввод -----------------------------------------------------

const PATTERN_RU = {straight: 'шов в шов', brick: 'вразбежку', diagonal: 'диагональ', herringbone: 'ёлочка'};

/** Быстрый ввод — ОДИН экран (как в макете), а не 12 шагов. Тонкая настройка
 * свёрнута и уже проставлена. Валидация — под полем, не общей плашкой. */
function screenCreate() {
  const d = state.draft;
  d.mode = d.mode || 'room';
  d.kind = d.kind || 'wall';
  d.errors = d.errors || {};
  d.adv = d.adv || false;
  d.tuning = d.tuning || {
    with_floor: false, joint_mm: 2, thickness_mm: 9, per_pack: null,
    pattern: 'straight', start_from: 'auto', waste: 7, waterproofing: false,
  };

  const box = h(`<div class="screen">
    <div class="top"><button class="icon-btn" id="back">${icon('back')}</button><h1>Новый объект</h1></div>
    <div id="form"></div>
    <div class="dock"><button class="btn" id="calc">Посчитать</button></div>
  </div>`);
  const form = box.querySelector('#form');

  const field = (label, key, ph, help, numeric = true) => {
    const f = h(`<label class="field"><span class="lab">${esc(label)}</span>
      <input type="text" ${numeric ? 'inputmode="decimal"' : ''} class="${d.errors[key] ? 'bad' : ''}" placeholder="${esc(ph)}" value="${esc(d[key] || '')}">
      ${help ? `<span class="help">${esc(help)}</span>` : ''}
      ${d.errors[key] ? `<span class="err">${esc(d.errors[key])}</span>` : ''}</label>`).firstElementChild;
    const inp = f.querySelector('input');
    inp.oninput = () => { d[key] = inp.value; };
    form.append(f);
  };

  field('Название объекта', 'title', 'Ванная, Борзова', '', false);

  form.append(h(`<div style="height:14px"></div>`));
  form.append(seg([['Комната целиком', 'room'], ['Одна поверхность', 'single']], d.mode,
    (v) => { d.mode = v; render(); }));

  if (d.mode === 'room') {
    field('Стены по кругу, м', 'wallsText', '2 1.8 2 1.8', 'по часовой, через пробел — как мерил');
    field('Высота, м', 'heightText', '2.7');
  } else {
    blockRow(form, 'grid', 'Что меряем', seg([['Стена', 'wall'], ['Пол', 'floor']], d.kind,
      (v) => { d.kind = v; render(); }));
    field('Размер, м', 'sizeText', '2 2.7', 'ширина и высота');
  }
  field('Плитка, см', 'tileText', '60 30', 'можно в см (60 30) или мм (600 300)');

  buildTuning(form, d);

  box.querySelector('#calc').onclick = () => run(() => createProject(d));
  box.querySelector('#back').onclick = () => { state.draft = null; loadList(); };
  return box;
}

/** «Тонкая настройка» — свёрнута с итогом-строкой, разворачивается. */
function buildTuning(el, d) {
  const tn = d.tuning;
  const sum = `шов ${fmtNum(tn.joint_mm)} мм · ${PATTERN_RU[tn.pattern]} · запас ${tn.waste}%`;
  const head = h(`<button class="tuning-head">${icon('grid', 'ic')}
    <span class="grow"><span>Тонкая настройка</span><span class="sum">${esc(sum)} — проставлено</span></span>
    ${icon(d.adv ? 'minus' : 'plus', 'ic')}</button>`).firstElementChild;
  head.onclick = () => { d.adv = !d.adv; render(); };
  el.append(head);
  if (!d.adv) return;

  const b = h(`<div class="tuning-body"></div>`).firstElementChild;
  const redraw = () => render();
  if (d.mode === 'room') toggleRow(b, 'grid', 'Пол своей плиткой', tn.with_floor, (v) => { tn.with_floor = v; redraw(); });
  valueRow(b, 'grid', 'Шов', {value: tn.joint_mm, fmt: (v) => `${fmtNum(v)} мм`, min: 0.5, max: 10, step: 0.5, onSet: (v) => { tn.joint_mm = v; redraw(); }});
  valueRow(b, 'box', 'Толщина плитки', {value: tn.thickness_mm, fmt: (v) => `${fmtNum(v)} мм`, min: 3, max: 30, step: 1, onSet: (v) => { tn.thickness_mm = v; redraw(); }});
  // штук в упаковке — пусто = не знаю, считаю штуками
  const pack = h(`<label class="field"><span class="lab">Штук в упаковке</span>
    <input type="text" inputmode="numeric" placeholder="не знаю — посчитаю штуками" value="${tn.per_pack || ''}"></label>`).firstElementChild;
  pack.querySelector('input').oninput = (e) => { const n = parseInt(e.target.value, 10); tn.per_pack = Number.isFinite(n) && n > 0 ? n : null; };
  b.append(pack);
  blockRow(b, 'layers', 'Раскладка', seg(PATTERNS, tn.pattern, (v) => { tn.pattern = v; redraw(); }));
  blockRow(b, 'ruler', 'Начало ряда', seg([['От угла', 'edge'], ['От центра', 'center'], ['Реши сам', 'auto']], tn.start_from, (v) => { tn.start_from = v; redraw(); }));
  valueRow(b, 'package', 'Запас', {value: tn.waste, fmt: (v) => `${Math.round(v)}%`, min: 0, max: 30, step: 1, onSet: (v) => { tn.waste = v; redraw(); }});
  toggleRow(b, 'droplet', 'Гидроизоляция', tn.waterproofing, (v) => { tn.waterproofing = v; redraw(); });
  el.append(b);
}

/** Разобрать поле сервером; ошибку — в d.errors[key], вернуть null. */
async function parseField(text, kind, key, d) {
  try { return (await measure(kind, text || '')).values; }
  catch (e) { d.errors[key] = e.message; return null; }
}

async function createProject(d) {
  d.errors = {};
  if (!(d.title || '').trim()) { d.errors.title = 'Напиши название объекта.'; render(); return; }

  let walls, height, size;
  const tile = await parseField(d.tileText, 'tile', 'tileText', d);
  if (d.mode === 'room') {
    walls = await parseField(d.wallsText, 'walls', 'wallsText', d);
    height = await parseField(d.heightText, 'height', 'heightText', d);
  } else {
    size = await parseField(d.sizeText, 'size', 'sizeText', d);
  }
  if (Object.keys(d.errors).length) { render(); return; }

  const tn = d.tuning;
  const common = {
    tile: {width_mm: tile[0], height_mm: tile[1], joint_mm: tn.joint_mm, thickness_mm: tn.thickness_mm, per_pack: tn.per_pack},
    pattern: tn.pattern, start_from: tn.start_from, waste: tn.waste / 100, waterproofing: tn.waterproofing,
  };
  const pr = await api('/api/projects', {method: 'POST', body: {title: d.title.trim()}});
  try {
    if (d.mode === 'room') {
      await api(`/api/projects/${pr.id}/room`, {method: 'POST', body: {...common, walls_m: walls, height_m: height[0], with_floor: !!tn.with_floor}});
    } else {
      await api(`/api/projects/${pr.id}/surface`, {method: 'POST', body: {...common, kind: d.kind, width_m: size[0], height_m: size[1]}});
    }
  } catch (e) {
    // напр. кривая комната + пол → 422; покажем у поля стен, объект-пустышку удалим
    await api(`/api/projects/${pr.id}`, {method: 'DELETE'}).catch(() => {});
    d.errors[d.mode === 'room' ? 'wallsText' : 'sizeText'] = e.message;
    render();
    return;
  }
  state.draft = null;
  // Показываем ХАБ объекта: плитка появится там первой работой, рядом «+ работа».
  state.object = await api(`/api/objects/${pr.id}`);
  state.screen = 'object';
}

// --- сборка ------------------------------------------------------------------

const loadList = () => run(async () => { state.projects = await api('/api/projects'); state.project = null; state.screen = 'list'; });

function skeletonList() {
  return h(`<div class="screen"><div class="top"><h1>Мои объекты</h1></div>
    <div class="skel skel-card"></div><div class="skel skel-card"></div><div class="skel skel-card"></div></div>`);
}

function render() {
  const screens = {
    list: screenList, create: screenCreate, object: screenObject,
    addwork: screenAddWork, work: screenWork, canvas: screenCanvas,
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
  if (s === 'object' || s === 'price') loadList();
  else if (s === 'create') { state.draft = null; loadList(); }
  else if (s === 'paper') (state.paper?.fromObject ? go('object') : go('canvas'));
  else if (s === 'buy') go('canvas');
  else backToObject();
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
