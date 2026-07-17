/* Мини-апп плиточника.
 *
 * Ничего не считает: все числа приходят с сервера, из того же ядра, что у бота.
 * Соблазн посчитать площадь «прямо тут, это же одна строка» — то, из-за чего
 * мини-апп начнёт спорить с ботом. Не считаем даже площадь.
 *
 * Разбор ввода («2 1.8 2 1.8», «60х30», «2,7») тоже на сервере: парсер уже
 * выстрадан на том, как Саня реально пишет.
 */

const tg = window.Telegram?.WebApp;
const root = document.getElementById('app');

const state = {
  screen: 'list',
  projects: [],
  project: null,   // {id, title, result, ...}
  paper: null,     // смета или акт
  price: null,
  draft: null,     // замеры, которые мастер сейчас вводит
  scheme: 0,
  busy: false,
};

// --- сервер ------------------------------------------------------------------

async function api(path, {method = 'GET', body} = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Init-Data': tg?.initData || '',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.error || 'Что-то пошло не так на сервере.');
  return data;
}

/** Показать ошибку человеку и не делать вид, что всё хорошо. */
function fail(e) {
  console.error(e);
  state.busy = false;
  render();
  const box = document.createElement('div');
  box.className = 'error';
  box.textContent = e.message;
  root.querySelector('.screen')?.prepend(box);
  tg?.HapticFeedback?.notificationOccurred('error');
}

/* Обёртка вокруг действия мастера: пока запрос летит, второе нажатие игнорируем.
 *
 * Звать run() ИЗНУТРИ run() нельзя: вложенный увидит busy и молча выйдет — на
 * этом уже потерялась кнопка «Гидроизоляция» в конце всех замеров. Внутри
 * обработчика просто зови async-функцию, без обёртки. Поэтому здесь не тихий
 * return, а крик в консоль: ошибка программиста должна быть видна. */
async function run(fn) {
  if (state.busy) {
    console.warn('run() уже занят — действие пропущено. Вложенный run()?');
    return;
  }
  state.busy = true;
  try {
    await fn();
    state.busy = false;
    render();
  } catch (e) {
    fail(e);
  }
}

/** Разобрать ввод мастера сервером — тем же парсером, что у бота. */
const measure = (kind, text) => api('/api/measure', {method: 'POST', body: {kind, text}});

// --- помощники разметки ------------------------------------------------------

const h = (html) => {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content;
};

const esc = (s) => String(s ?? '').replace(/[<>&"]/g, (c) =>
  ({'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c]));

const money = (v) => `${Math.round(v).toLocaleString('ru-RU').replace(/ /g, ' ')} ₽`;

const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  return b === 1 ? one : many;
};

function go(screen) {
  state.screen = screen;
  render();
}

// --- экран: список объектов --------------------------------------------------

function screenList() {
  const box = h(`
    <div class="screen">
      <h1>Мои объекты</h1>
      <div id="list"></div>
      <button class="btn" id="new">➕ Новый объект</button>
      <button class="btn secondary" id="price">💰 Прайс</button>
    </div>
  `);
  const list = box.querySelector('#list');

  if (!state.projects.length) {
    list.append(h(`<div class="empty">Объектов пока нет.<br>Заведи первый — посчитаем.</div>`));
  }

  for (const p of state.projects) {
    const due = p.due > 0
      ? `<span class="badge due">${money(p.due)}</span>`
      : p.deal_amount ? `<span class="badge paid">рассчитались</span>` : '';
    const card = h(`
      <button class="card project">
        <div class="row">
          <span class="project-title">${esc(p.title)}</span>
          ${due}
        </div>
        <div class="hint">${p.surfaces} ${plural(p.surfaces, 'поверхность', 'поверхности', 'поверхностей')}</div>
      </button>
    `);
    card.querySelector('button').onclick = () => openProject(p.id);
    list.append(card);
  }

  box.querySelector('#new').onclick = () => {
    state.draft = {step: 'title', title: '', mode: null};
    go('measure');
  };
  box.querySelector('#price').onclick = () => run(async () => {
    state.price = (await api('/api/me')).price;
    state.screen = 'price';
  });
  return box;
}

const openProject = (id) => run(async () => {
  state.project = await api(`/api/projects/${id}`);
  state.scheme = 0;
  state.screen = 'project';
});

// --- экран: замеры -----------------------------------------------------------

/* Один вопрос — один экран, как в боте. Саня меряет стоя на объекте, и простыня
   из пятнадцати полей на телефоне ему не нужна. */
function screenMeasure() {
  const d = state.draft;
  const steps = {
    title: () =>
      ask('Как назовём объект?', 'Ванная, Борзова 12', 'text', (v) => {
        if (!v.trim()) throw new Error('Напиши название объекта.');
        d.title = v.trim();
        d.step = 'mode';
      }),

    mode: () => choose('Что считаем?', [
      ['🛁 Комната целиком', () => { d.mode = 'room'; d.step = 'walls'; }],
      ['▭ Одна стена или пол', () => { d.mode = 'single'; d.step = 'kind'; }],
    ]),

    walls: () =>
      ask('Обмерь комнату по кругу — длина каждой стены через пробел',
          '2 1.8 2 1.8', 'text', async (v) => {
        d.walls = (await measure('walls', v)).values;
        d.step = 'height';
      }, 'Сколько стен — столько чисел. Порядок — как обходишь комнату.'),

    height: () =>
      ask('Высота стен?', '2.7', 'text', async (v) => {
        d.height = (await measure('height', v)).values[0];
        d.step = d.walls.length === 4 ? 'floor' : 'tile';
        if (d.step === 'tile') d.with_floor = false;
      }),

    floor: () => choose('Пол тоже плиткой?', [
      ['Да, и пол', () => { d.with_floor = true; d.step = 'tile'; }],
      ['Только стены', () => { d.with_floor = false; d.step = 'tile'; }],
    ]),

    kind: () => choose('Что меряем?', [
      ['Стена', () => { d.kind = 'wall'; d.step = 'size'; }],
      ['Пол', () => { d.kind = 'floor'; d.step = 'size'; }],
    ]),

    size: () =>
      ask('Размер поверхности — ширина и высота', '2 2.7', 'text', async (v) => {
        const [w, hgt] = (await measure('size', v)).values;
        d.width_m = w; d.height_m = hgt;
        d.step = 'tile';
      }),

    tile: () =>
      ask('Размер плитки', '60 30', 'text', async (v) => {
        const [w, hgt] = (await measure('tile', v)).values;
        d.tile = {width_mm: w, height_mm: hgt};
        d.step = 'joint';
      }, 'Можно в сантиметрах («60 30») или в миллиметрах («600 300»).'),

    joint: () => chips('Какой шов?', ['1,5', '2', '3'], 'Свой размер', (v) => {
      d.tile.joint_mm = parseFloat(String(v).replace(',', '.'));
      if (!(d.tile.joint_mm >= 0)) throw new Error('Шов — это число.');
      d.step = 'thickness';
    }),

    thickness: () => chips('Толщина плитки, мм?', ['8', '9', '10'], 'Своя', (v) => {
      d.tile.thickness_mm = parseFloat(String(v).replace(',', '.'));
      if (!(d.tile.thickness_mm > 0)) throw new Error('Толщина — это число.');
      d.step = 'pack';
    }),

    pack: () =>
      ask('Сколько плиток в упаковке?', '8', 'number', (v) => {
        d.tile.per_pack = v ? parseInt(v, 10) : null;
        d.step = (d.mode === 'room' && d.with_floor) ? 'floor_tile' : 'pattern';
      }, 'Не знаешь — пропусти, посчитаю штуками.', true),

    floor_tile: () =>
      ask('Плитка на пол — размер', '60 60', 'text', async (v) => {
        if (!v.trim()) { d.floor_tile = null; d.step = 'pattern'; return; }
        const [w, hgt] = (await measure('tile', v)).values;
        d.floor_tile = {width_mm: w, height_mm: hgt, joint_mm: d.tile.joint_mm,
                        thickness_mm: d.tile.thickness_mm};
        d.step = 'floor_pack';
      }, 'Пропусти — положу такую же, как на стены.', true),

    floor_pack: () =>
      ask('Плиток в упаковке напольной?', '4', 'number', (v) => {
        d.floor_tile.per_pack = v ? parseInt(v, 10) : null;
        d.step = 'pattern';
      }, '', true),

    pattern: () => choose('Раскладка?', [
      ['Шов в шов', () => { d.pattern = 'straight'; d.step = 'start'; }],
      ['Вразбежку', () => { d.pattern = 'brick'; d.step = 'start'; }],
      ['Диагональ', () => { d.pattern = 'diagonal'; d.step = 'start'; }],
      ['Ёлочка', () => { d.pattern = 'herringbone'; d.step = 'start'; }],
    ]),

    start: () => choose('Откуда начинаем ряд?', [
      ['Как лучше — реши сам', () => { d.start_from = 'auto'; d.step = 'waste'; }],
      ['От угла', () => { d.start_from = 'edge'; d.step = 'waste'; }],
      ['От центра', () => { d.start_from = 'center'; d.step = 'waste'; }],
    ]),

    waste: () => {
      const advised = (d.pattern === 'diagonal' || d.pattern === 'herringbone') ? 15 : 7;
      return chips(`Запас на бой и подрезку? Под эту раскладку советую ${advised}%.`,
        ['7', '10', '15'], 'Свой', (v) => {
          const pct = parseFloat(String(v).replace(',', '.'));
          if (!(pct >= 0 && pct <= 100)) throw new Error('Запас — это проценты, 0–100.');
          d.waste = pct / 100;
          d.step = 'waterproof';
        }, String(advised));
    },

    waterproof: () => choose('Гидроизоляция нужна?', [
      ['Да, мокрая зона', () => save(true)],
      ['Не нужна', () => save(false)],
    ]),
  };

  /* Зовётся уже изнутри run() — своего run() здесь быть не должно: он увидел бы
     state.busy и молча вышел, а мастер остался бы с мёртвой кнопкой в конце всех
     замеров. */
  async function save(waterproofing) {
    const project = await api('/api/projects', {method: 'POST', body: {title: d.title}});
    const common = {
      tile: d.tile,
      floor_tile: d.floor_tile || null,
      pattern: d.pattern,
      start_from: d.start_from,
      waste: d.waste,
      waterproofing,
    };
    if (d.mode === 'room') {
      await api(`/api/projects/${project.id}/room`, {method: 'POST', body: {
        ...common, walls_m: d.walls, height_m: d.height, with_floor: !!d.with_floor,
      }});
    } else {
      await api(`/api/projects/${project.id}/surface`, {method: 'POST', body: {
        ...common, kind: d.kind, width_m: d.width_m, height_m: d.height_m,
      }});
    }
    state.draft = null;
    state.project = await api(`/api/projects/${project.id}`);
    state.scheme = 0;
    state.screen = 'project';
  }

  return steps[d.step]();
}

/** Вопрос с полем ввода. */
function ask(title, placeholder, type, onNext, hint = '', skippable = false) {
  const box = h(`
    <div class="screen">
      <h1>${esc(title)}</h1>
      ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}
      <input type="${type === 'number' ? 'number' : 'text'}"
             inputmode="${type === 'number' ? 'numeric' : 'text'}"
             placeholder="${esc(placeholder)}">
      <button class="btn" id="next">Дальше</button>
      ${skippable ? '<button class="btn secondary" id="skip">Пропустить</button>' : ''}
    </div>
  `);
  const input = box.querySelector('input');
  const submit = () => run(async () => { await onNext(input.value); });

  box.querySelector('#next').onclick = submit;
  box.querySelector('#skip')?.addEventListener('click', () => run(async () => {
    await onNext('');
  }));
  setTimeout(() => input.focus(), 50);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  return box;
}

/** Вопрос с кнопками-вариантами. */
function choose(title, options) {
  const box = h(`<div class="screen"><h1>${esc(title)}</h1></div>`);
  for (const [label, onPick] of options) {
    const btn = h(`<button class="btn secondary">${esc(label)}</button>`);
    btn.querySelector('button').onclick = () => run(async () => { await onPick(); });
    box.querySelector('.screen').append(btn);
  }
  return box;
}

/** Вопрос с частыми ответами и возможностью вписать своё — как кнопки в боте. */
function chips(title, values, ownLabel, onPick, preset = '') {
  const box = h(`
    <div class="screen">
      <h1>${esc(title)}</h1>
      <div class="chips">
        ${values.map((v) => `<button class="chip" data-v="${esc(v)}">${esc(v)}</button>`).join('')}
      </div>
      <label>${esc(ownLabel)}</label>
      <input type="text" inputmode="decimal" value="${esc(preset)}">
      <button class="btn" id="next">Дальше</button>
    </div>
  `);
  for (const chip of box.querySelectorAll('.chip')) {
    chip.onclick = () => run(async () => { await onPick(chip.dataset.v); });
  }
  const input = box.querySelector('input');
  box.querySelector('#next').onclick = () => run(async () => { await onPick(input.value); });
  return box;
}

// --- экран: посчитанный объект -----------------------------------------------

function screenProject() {
  const p = state.project;
  const r = p.result;

  if (!r) {
    const box = h(`
      <div class="screen">
        <h1>${esc(p.title)}</h1>
        <div class="empty">В объекте пока нет поверхностей.</div>
        <button class="btn secondary" id="back">← К объектам</button>
      </div>
    `);
    box.querySelector('#back').onclick = () => loadList();
    return box;
  }

  const t = r.tile;
  const head = r.surfaces.length === 1
    ? `${esc(r.surfaces[0].name)} — ${r.area_m2.toFixed(2)} м²`
    : `Комната целиком — ${r.walls} ${plural(r.walls, 'стена', 'стены', 'стен')}` +
      `${r.has_floor ? ' + пол' : ''}, ${r.area_m2.toFixed(2)} м²${r.wrap ? ' · эконом по кругу' : ''}`;

  const box = h(`
    <div class="screen">
      <div class="row">
        <div class="summary-head">${esc(p.title)}</div>
        <button class="badge" id="back">← объекты</button>
      </div>
      <p class="hint">${head}</p>

      <div class="scheme-nav">
        ${r.surfaces.map((s, i) =>
          `<button class="chip ${i === state.scheme ? 'on' : ''}" data-i="${i}">${esc(s.name)}</button>`
        ).join('')}
      </div>
      <img class="scheme" alt="Схема раскладки">

      <div class="card">
        <div>Плитка ${t.width_mm.toFixed(0)}×${t.height_mm.toFixed(0)}
             (${t.lying ? 'лёжа' : 'стоя'}), шов ${esc(t.joint_text)} мм</div>
        <div>Класть: <b>${r.tiles_grid} шт</b> (резаных ${r.cuts_count})</div>
      </div>

      ${r.savings ? `<div class="savings">💰 Эконом сберёг ${r.savings.tiles}
        ${plural(r.savings.tiles, 'плитку', 'плитки', 'плиток')}${r.savings.packs
          ? ` — это ${r.savings.packs} ${plural(r.savings.packs, 'упаковка', 'упаковки', 'упаковок')}` : ''}:
        остатки уходят за угол, а не в мусор.</div>` : ''}

      <h2>Купить</h2>
      <ul class="buy">
        ${r.purchase.map((m) => `<li>${esc(m.name)}: <b>${esc(m.qty_text)} ${esc(m.unit)}</b>
          ${m.note ? `<span class="note">(${esc(m.note)})</span>` : ''}</li>`).join('')}
      </ul>
      ${r.tile_cost ? `<p class="hint">Плитка на ${money(r.tile_cost)}</p>` : ''}

      <div class="actions" id="actions"></div>

      ${r.advice.map((a) => `<div class="advice">💡 ${esc(a)}</div>`).join('')}

      <button class="btn secondary" id="paper-est">💵 Смета заказчику</button>
      <button class="btn secondary" id="paper-act">📄 Акт выполненных работ</button>
      <button class="btn secondary" id="money">💵 Деньги по объекту</button>
      <button class="btn danger" id="del">Удалить объект</button>
    </div>
  `);

  // Схема — картинкой с сервера: рисует тот же render_layout, что шлёт бот.
  const img = box.querySelector('.scheme');
  img.src = `/api/projects/${p.id}/scheme/${state.scheme}.png?v=${Date.now()}`;
  // Схему отдаёт защищённая ручка, а <img> заголовок не пришлёт — грузим сами.
  loadScheme(img, p.id, state.scheme);

  for (const chip of box.querySelectorAll('.scheme-nav .chip')) {
    chip.onclick = () => { state.scheme = +chip.dataset.i; render(); };
  }

  const patch = (body) => run(async () => {
    state.project.result = await api(`/api/projects/${p.id}`, {method: 'PATCH', body});
    tg?.HapticFeedback?.impactOccurred('light');
  });

  const actions = box.querySelector('#actions');
  const add = (label, fn, wide = false) => {
    const b = h(`<button class="btn secondary ${wide ? 'wide' : ''}">${esc(label)}</button>`);
    b.querySelector('button').onclick = fn;
    actions.append(b);
  };

  add('🔀 Раскладка', () => go('pattern'));
  add('↔️ Начало ряда', () => go('start'));
  if (r.can_wrap) {
    add(r.wrap ? '📐 Вернуть обычную' : '💰 Эконом: по кругу',
        () => patch({wrap: !r.wrap}), true);
  }
  if (r.pattern === 'brick') add('🧱 Смещение', () => go('offset'));
  add('🔄 Повернуть плитку', () => patch({rotate: true}));
  add('📏 Размер плитки', () => go('resize'));
  add('🎨 Цвет затирки', () => go('grout'));
  add('🧴 Вид затирки', () => go('groutkind'));

  box.querySelector('#back').onclick = () => loadList();
  box.querySelector('#paper-est').onclick = () => openPaper('estimate');
  box.querySelector('#paper-act').onclick = () => openPaper('act');
  box.querySelector('#money').onclick = () => go('money');
  box.querySelector('#del').onclick = () => {
    const ok = () => run(async () => {
      await api(`/api/projects/${p.id}`, {method: 'DELETE'});
      state.project = null;
      state.projects = await api('/api/projects');
      state.screen = 'list';
    });
    if (tg?.showConfirm) tg.showConfirm(`Удалить «${p.title}»?`, (yes) => yes && ok());
    else if (confirm(`Удалить «${p.title}»?`)) ok();
  };
  return box;
}

/** Схема лежит за проверкой initData — тянем с заголовком и показываем blob. */
async function loadScheme(img, projectId, index) {
  try {
    const res = await fetch(`/api/projects/${projectId}/scheme/${index}.png`, {
      headers: {'X-Init-Data': tg?.initData || ''},
    });
    if (!res.ok) return;
    img.src = URL.createObjectURL(await res.blob());
  } catch (e) {
    console.error(e);
  }
}

// --- экраны правок -----------------------------------------------------------

function screenPick(title, options, patchOf, hint = '') {
  const r = state.project.result;
  const box = h(`
    <div class="screen">
      <h1>${esc(title)}</h1>
      ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}
      <div class="chips">
        ${options.map(([label, value, on]) =>
          `<button class="chip ${on ? 'on' : ''}" data-v="${esc(value)}">${esc(label)}</button>`
        ).join('')}
      </div>
      <button class="btn secondary" id="back">← Назад</button>
    </div>
  `);
  for (const chip of box.querySelectorAll('.chip')) {
    chip.onclick = () => run(async () => {
      state.project.result = await api(`/api/projects/${state.project.id}`, {
        method: 'PATCH', body: patchOf(chip.dataset.v),
      });
      state.screen = 'project';
    });
  }
  box.querySelector('#back').onclick = () => go('project');
  void r;
  return box;
}

const PATTERNS = [
  ['Шов в шов', 'straight'], ['Вразбежку', 'brick'],
  ['Диагональ', 'diagonal'], ['Ёлочка', 'herringbone'],
];
const GROUTS = [
  ['Белая', 'white'], ['Серая', 'grey'], ['Бежевая', 'beige'],
  ['Графит', 'graphite'], ['Чёрная', 'black'],
];

function screenResize() {
  const r = state.project.result;
  const box = h(`
    <div class="screen">
      <h1>Размер плитки</h1>
      <p class="hint">Прикинуть «а если взять другую» — замеры вводить заново не надо.</p>
      <label>Куда</label>
      <div class="chips">
        <button class="chip on" data-k="wall">На стены</button>
        ${r.has_floor ? '<button class="chip" data-k="floor">На пол</button>' : ''}
      </div>
      <label>Новый размер</label>
      <input type="text" placeholder="120 60">
      <button class="btn" id="go">Пересчитать</button>
      <button class="btn secondary" id="back">← Назад</button>
    </div>
  `);
  let kind = 'wall';
  for (const chip of box.querySelectorAll('.chip')) {
    chip.onclick = () => {
      kind = chip.dataset.k;
      box.querySelectorAll('.chip').forEach((c) => c.classList.toggle('on', c === chip));
    };
  }
  box.querySelector('#go').onclick = () => run(async () => {
    const [w, hgt] = (await measure('tile', box.querySelector('input').value)).values;
    state.project.result = await api(`/api/projects/${state.project.id}`, {
      method: 'PATCH', body: {tile_size: {width_mm: w, height_mm: hgt, kind}},
    });
    state.screen = 'project';
  });
  box.querySelector('#back').onclick = () => go('project');
  return box;
}

// --- экран: смета и акт ------------------------------------------------------

const openPaper = (kind) => run(async () => {
  state.paper = await api(`/api/projects/${state.project.id}/${kind}`);
  state.paper.kind = kind;
  state.screen = 'paper';
});

function screenPaper() {
  const e = state.paper;
  const isAct = e.kind === 'act';
  const box = h(`
    <div class="screen">
      <h1>${isAct ? 'Акт выполненных работ' : 'Смета'} — ${esc(e.title)}</h1>

      <h2>Работы</h2>
      ${e.works.map((w) => `
        <div class="paper-line">
          <div>${esc(w.name)}<div class="qty">${w.qty}${w.unit ? ' ' + esc(w.unit) : ''}
            ${w.unit ? '× ' + money(w.price) : ''}</div></div>
          <div><b>${esc(w.total_text)}</b></div>
        </div>`).join('')}
      <div class="paper-total"><span>РАБОТА</span><span>${esc(e.works_total_text)}</span></div>

      <h2>${isAct ? 'Материалы' : 'Материалы — купить'}</h2>
      ${e.materials.map((m) => `
        <div class="paper-line">
          <div>${esc(m.name)}<div class="qty">${esc(m.qty_text)} ${esc(m.unit)}${
            m.packs ? ` (${m.packs} уп.)` : ''}</div></div>
          <div class="muted">${m.cost ? '≈ ' + money(m.cost) : ''}</div>
        </div>`).join('')}

      ${isAct
        ? `<div class="paper-total"><span>ИТОГО К ОПЛАТЕ</span><span>${esc(e.grand_total_text)}</span></div>`
        : `<div class="paper-total"><span>ВСЁ ВМЕСТЕ ≈</span><span>${esc(e.rough_total_text)}</span></div>
           <p class="hint">Материалы заказчик покупает сам, в стоимость работы они не входят.
           Цены примерные, для ориентира — можно взять дешевле или дороже.</p>`}

      ${e.note ? `<p class="hint">${esc(e.note)}</p>` : ''}
      <button class="btn secondary" id="back">← К объекту</button>
    </div>
  `);
  box.querySelector('#back').onclick = () => go('project');
  return box;
}

// --- экран: прайс ------------------------------------------------------------

const PRICE_FIELDS = [
  ['wall_tiling', 'Укладка на стену, ₽/м²'],
  ['floor_tiling', 'Укладка на пол, ₽/м²'],
  ['cutting', 'Подрезка плитки, ₽/шт'],
  ['grouting', 'Затирка цементной, ₽/м²'],
  ['grouting_epoxy', 'Затирка эпоксидной, ₽/м²'],
  ['waterproofing', 'Гидроизоляция, ₽/м²'],
  ['priming', 'Грунтовка, ₽/м²'],
  ['demolition', 'Демонтаж старой плитки, ₽/м²'],
  ['min_order', 'Минимальный чек за выезд, ₽'],
];

function screenPrice() {
  const box = h(`
    <div class="screen">
      <h1>Прайс</h1>
      <p class="hint">Твои расценки — по ним считается смета.</p>
      ${PRICE_FIELDS.map(([key, label]) => `
        <label>${esc(label)}</label>
        <input type="number" inputmode="decimal" data-k="${key}" value="${state.price[key]}">
      `).join('')}
      <button class="btn" id="save">Сохранить</button>
      <button class="btn secondary" id="back">← Назад</button>
    </div>
  `);
  box.querySelector('#save').onclick = () => run(async () => {
    const body = {};
    for (const input of box.querySelectorAll('input[data-k]')) {
      body[input.dataset.k] = parseFloat(input.value || '0');
    }
    state.price = await api('/api/price', {method: 'PUT', body});
    tg?.HapticFeedback?.notificationOccurred('success');
    state.screen = 'list';
  });
  box.querySelector('#back').onclick = () => loadList();
  return box;
}

// --- экран: деньги -----------------------------------------------------------

function screenMoney() {
  const p = state.project;
  const box = h(`
    <div class="screen">
      <h1>Деньги — ${esc(p.title)}</h1>
      <div class="card">
        <div class="row"><span>Договорились</span><b>${money(p.deal_amount)}</b></div>
        <div class="row"><span>Получено</span><b>${money(p.paid)}</b></div>
        <div class="row"><span>Остаток с заказчика</span>
          <b class="${p.due > 0 ? 'badge due' : 'badge paid'}">${money(p.due)}</b></div>
      </div>

      <label>Сумма договора, ₽</label>
      <input type="number" inputmode="decimal" id="deal" value="${p.deal_amount || ''}">
      <button class="btn secondary" id="save-deal">Записать договор</button>

      <label>Получил от заказчика, ₽</label>
      <div class="field-pair">
        <input type="number" inputmode="decimal" id="pay" placeholder="30000">
        <input type="text" id="comment" placeholder="аванс">
      </div>
      <button class="btn" id="add-pay">Записать приход</button>

      ${p.payments.length ? '<h2>Приходы</h2>' : ''}
      ${p.payments.map((x) => `
        <div class="paper-line">
          <div>${esc(x.comment || 'платёж')}<div class="qty">${esc(x.at.slice(0, 10))}</div></div>
          <div><b>${money(x.amount)}</b></div>
        </div>`).join('')}

      <button class="btn secondary" id="back">← К объекту</button>
    </div>
  `);
  box.querySelector('#save-deal').onclick = () => run(async () => {
    const amount = parseFloat(box.querySelector('#deal').value || '0');
    Object.assign(state.project, await api(`/api/projects/${p.id}/deal`,
      {method: 'PUT', body: {amount}}));
  });
  box.querySelector('#add-pay').onclick = () => run(async () => {
    const amount = parseFloat(box.querySelector('#pay').value || '0');
    if (!(amount > 0)) throw new Error('Сумма прихода — больше нуля.');
    Object.assign(state.project, await api(`/api/projects/${p.id}/payments`, {
      method: 'POST', body: {amount, comment: box.querySelector('#comment').value},
    }));
  });
  box.querySelector('#back').onclick = () => go('project');
  return box;
}

// --- сборка ------------------------------------------------------------------

const loadList = () => run(async () => {
  state.projects = await api('/api/projects');
  state.project = null;
  state.screen = 'list';
});

function render() {
  const r = state.project?.result;
  const screens = {
    list: screenList,
    measure: screenMeasure,
    project: screenProject,
    paper: screenPaper,
    price: screenPrice,
    money: screenMoney,
    resize: screenResize,
    pattern: () => screenPick('Раскладка',
      PATTERNS.map(([l, v]) => [l, v, r.pattern === v]), (v) => ({pattern: v}),
      'Посмотреть, как выйдет иначе. Замеры не пропадут.'),
    start: () => screenPick('Начало ряда', [
      ['От угла', 'edge', r.start_from === 'edge'],
      ['От центра', 'center', r.start_from === 'center'],
    ], (v) => ({start_from: v}), 'От угла — вся подрезка справа; от центра — поровну по краям.'),
    offset: () => screenPick('Смещение рядов', [
      ['1/2', '1/2', Math.abs(r.offset_ratio - 0.5) < 1e-6],
      ['1/3 (палубная)', '1/3', Math.abs(r.offset_ratio - 1 / 3) < 1e-6],
      ['1/4', '1/4', Math.abs(r.offset_ratio - 0.25) < 1e-6],
    ], (v) => ({offset_label: v})),
    grout: () => screenPick('Цвет затирки',
      GROUTS.map(([l, v]) => [l, v, r.grout === v]), (v) => ({grout: v})),
    groutkind: () => screenPick('Вид затирки', [
      ['Цементная', 'cement', r.grout_kind === 'cement'],
      ['Эпоксидная', 'epoxy', r.grout_kind === 'epoxy'],
    ], (v) => ({grout_kind: v}),
       'Эпоксидную дольше затирать — это дороже в работе, и расход у неё другой.'),
  };

  root.replaceChildren(screens[state.screen]());

  // Кнопка «назад» в шапке Telegram — на списке она не нужна.
  if (tg?.BackButton) {
    if (state.screen === 'list') tg.BackButton.hide();
    else tg.BackButton.show();
  }
}

tg?.ready();
tg?.expand();
tg?.BackButton?.onClick(() => {
  if (state.screen === 'project' || state.screen === 'price') loadList();
  else if (state.screen === 'measure') { state.draft = null; loadList(); }
  else go('project');
});

/* Апп открыт вне Telegram (по ссылке в браузере) — initData пустой, и сервер
   ответит 401. Не бьёмся в него молча: объясняем, что открыть надо кнопкой в
   боте. Именно этот случай выглядел как «не удалось опознать». */
if (!tg || !tg.initData) {
  root.replaceChildren(h(`
    <div class="screen">
      <div class="empty">
        <h1>Откройте через бота</h1>
        <p>Это приложение помощника плиточника. Оно открывается кнопкой
        <b>«Приложение»</b> слева от поля ввода в чате с ботом — там Telegram
        передаёт, кто вы.</p>
        <p class="hint">Ссылку в обычном браузере открывать не нужно: там нет
        вашей учётки, и объекты не подтянутся.</p>
      </div>
    </div>
  `));
} else {
  loadList();
}
