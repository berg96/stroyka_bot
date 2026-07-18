/* Прогон экранов мини-аппа v2 (холст) в jsdom: экраны рисуются, живой пересчёт
 * шлёт PATCH и обновляет числа, степпер шва и ввод с клавиатуры работают, вьюер
 * схемы открывается, вне-Telegram показывает инструкцию. Сервер поддельный, но
 * отвечает тем же, что настоящий API. Запуск: node smoke.js */
const {JSDOM} = require('jsdom');
const fs = require('fs');
const APP = require('path').join(__dirname, '../../src/tilebot/web/static/app.js');

const baseResult = () => ({
  area_m2: 24.12, tiles_grid: 145, cuts_count: 40, walls: 4, has_floor: true,
  can_wrap: true, wrap: false, pattern: 'brick', start_from: 'edge', offset_ratio: 0.5,
  grout: null, grout_kind: 'cement', waste: 0.07, waterproofing: true, tile_locked: false,
  tile_photo: false,
  tile: {width_mm: 600, height_mm: 300, joint_mm: 1.4, joint_text: '1,4', thickness_mm: 9,
         per_pack: 8, price_per_m2: null, lying: true},
  tile_cost: null,
  surfaces: [
    {index: 0, name: 'Стена 1', kind: 'wall', area_m2: 5.4, tiles: 36, cuts: 10, tile_w: 600, tile_h: 300, openings: []},
    {index: 1, name: 'Пол', kind: 'floor', area_m2: 3.6, tiles: 13, cuts: 4, tile_w: 600, tile_h: 600, openings: []},
  ],
  purchase: [{name: 'Плитка 600×300', qty: 131, qty_text: '131', unit: 'шт', note: '23.6 м² с запасом 7%, ≈17 уп.', kind: 'tile'}],
  advice: ['Раскладка ровная'], savings: null,
});
const PROJECT = {id: 1, title: 'Ванная, Борзова', surfaces: 5, photos: 0, deal_amount: 50000, paid: 20000, due: 30000, payments: [], result: baseResult()};
const OBJECT = () => ({
  id: 1, title: 'Ванная, Борзова', surfaces: 5, photos: 0, deal_amount: 50000, paid: 20000, due: 30000, payments: [],
  measures: {walls: [2, 1.8, 2, 1.8], height_m: 2.7, floor_m2: 2.9},
  works: [{id: 'tile', kind: 'tile', name: 'Плитка', input: {}, hero_value: '23,4 м²', hero_note: '156 плиток', work_sum: 34710}],
  total: 34710,
});
const laminateWork = (underlay = true) => ({
  id: 10, kind: 'laminate', name: 'Ламинат', input: {pack_m2: 2.1, waste: 0.05, underlay},
  hero_value: '2,9 м²', hero_note: '2 пачек', work_sum: 1764,
  work_lines: [{name: 'Укладка ламината', qty: 2.9, unit: 'м²', total: 1764, total_text: '1 764 ₽'}],
  materials: underlay
    ? [{name: 'Ламинат', qty_text: '2', unit: 'пачек', note: ''}, {name: 'Подложка', qty_text: '2,9', unit: 'м²', note: ''}]
    : [{name: 'Ламинат', qty_text: '2', unit: 'пачек', note: ''}],
});

function makeApp({initData = 'user=%7B%22id%22%3A1%7D&hash=x'} = {}) {
  const calls = [];
  const dom = new JSDOM(`<!doctype html><body><div id="app"></div></body>`, {runScripts: 'outside-only', url: 'https://plitka.example/'});
  const w = dom.window;
  w.Telegram = {WebApp: {initData, ready() {}, expand() {},
    HapticFeedback: {impactOccurred() {}, notificationOccurred() {}},
    BackButton: {show() {}, hide() {}, onClick() {}}}};
  w.URL.createObjectURL = () => 'blob:scheme';
  w.fetch = async (url, o = {}) => {
    const m = o.method || 'GET';
    const body = o.body ? JSON.parse(o.body) : null;
    calls.push({m, url, body});
    if (/scheme\/\d+\.png/.test(url)) return {ok: true, status: 200, blob: async () => new w.Blob([1])};
    if (/\/api\/measure$/.test(url)) {
      // те же пороги, что бэкенд: плитка в см (<200 → ×10)
      const nums = body.text.trim().split(/[\s,;xх*×]+/).map((x) => parseFloat(x.replace(',', '.')));
      const conv = body.kind === 'tile' ? nums.map((v) => v < 200 ? v * 10 : v)
        : body.kind === 'walls' || body.kind === 'height' ? nums.map((v) => v < 20 ? v : v / 1000)
          : nums.map((v) => (v < 20 ? v * 1000 : v) / 1000);
      return {ok: true, status: 200, json: async () => ({values: conv})};
    }
    if (/\/api\/projects$/.test(url) && m === 'POST') return {ok: true, status: 201, json: async () => ({id: 1, title: body.title})};
    if (/\/api\/projects\/1\/(room|surface)$/.test(url)) return {ok: true, status: 201, json: async () => baseResult()};
    if (/\/deal$/.test(url)) return {ok: true, status: 200, json: async () => ({...PROJECT, deal_amount: body.amount, due: body.amount})};
    if (/\/payments$/.test(url)) return {ok: true, status: 201, json: async () => ({...PROJECT, paid: body.amount, due: 0, payments: [{amount: body.amount, comment: body.comment, at: '2026-07-18T03:00:00'}]})};
    if (/\/title$/.test(url)) return {ok: true, status: 200, json: async () => ({...PROJECT, title: body.title})};
    if (/\/api\/me$/.test(url)) return {ok: true, status: 200, json: async () => ({id: 1, name: '', phone: '', price: {wall_tiling: 1200, floor_tiling: 1000, cutting: 60, grouting: 200, grouting_epoxy: 450, waterproofing: 400, priming: 100, demolition: 500, min_order: 0}})};
    if (/\/api\/price$/.test(url)) return {ok: true, status: 200, json: async () => body};
    if (/\/api\/objects\/1$/.test(url) && m === 'GET') return {ok: true, status: 200, json: async () => OBJECT()};
    if (/\/api\/objects\/1\/(estimate|act)$/.test(url)) return {ok: true, status: 200, json: async () => ({
      title: 'Ванная, Борзова',
      works: [{name: 'Укладка плитки', qty: 20.5, unit: 'м²', price: 1200, total: 24600, total_text: '24 600 ₽'},
              {name: 'Укладка ламината', qty: 2.9, unit: 'м²', price: 600, total: 1764, total_text: '1 764 ₽'}],
      works_total: 26364, works_total_text: '26 364 ₽',
      materials: [{name: 'Плитка 600×300', qty_text: '131', unit: 'шт', packs: 17, cost: 35400},
                  {name: 'Ламинат', qty_text: '2', unit: 'пачек', cost: 1800}],
      materials_total: 0, rough_materials_total: 37200, rough_total: 63564, rough_total_text: '63 564 ₽',
      grand_total: 63564, grand_total_text: '63 564 ₽', note: ''})};
    if (/\/api\/objects\/1\/works$/.test(url) && m === 'POST') return {ok: true, status: 201, json: async () => laminateWork()};
    if (/\/api\/objects\/1\/works\/10$/.test(url) && m === 'GET') return {ok: true, status: 200, json: async () => laminateWork()};
    if (/\/api\/objects\/1\/works\/10$/.test(url) && m === 'PATCH') return {ok: true, status: 200, json: async () => laminateWork(body.input.underlay !== false)};
    if (/\/api\/objects\/1\/works\/10$/.test(url) && m === 'DELETE') return {ok: true, status: 200, json: async () => ({ok: true})};
    if (/\/api\/projects$/.test(url) && m === 'GET') return {ok: true, status: 200, json: async () => [PROJECT]};
    if (/\/api\/projects\/1$/.test(url) && m === 'GET') return {ok: true, status: 200, json: async () => PROJECT};
    if (/\/api\/projects\/1$/.test(url) && m === 'PATCH') {
      // отражаем изменение: меняем результат по патчу, число «Купить» другое
      const r = baseResult();
      if (body.pattern) r.pattern = body.pattern;
      if (body.joint_mm != null) { r.tile.joint_mm = body.joint_mm; r.tile.joint_text = String(body.joint_mm).replace('.', ','); }
      r.tiles_grid = 150; // видимое изменение числа
      return {ok: true, status: 200, json: async () => r};
    }
    return {ok: true, status: 200, json: async () => baseResult()};
  };
  const errs = [];
  w.addEventListener('error', (e) => errs.push(e.error?.message || e.message));
  w.eval(fs.readFileSync(APP, 'utf8'));
  return {w, calls, errs};
}

const wait = (ms = 60) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, cond, extra = '') => {
  if (cond) return console.log(`  ✅ ${name}`);
  failed++; console.log(`  ❌ ${name}${extra ? ' — ' + extra : ''}`);
};
const byText = (w, sel, t) => [...w.document.querySelectorAll(sel)].find((e) => e.textContent.includes(t));

(async () => {
  console.log('Портфель → хаб объекта → холст плитки');
  const {w, calls, errs} = makeApp();
  await wait();
  check('список рисуется', w.document.body.textContent.includes('Ванная, Борзова'));
  byText(w, '.tile-row', 'Ванная').click();
  await wait(80);
  const t = () => w.document.body.textContent;
  check('хаб: раздел «Работы» и замеры', t().includes('Работы') && t().includes('Замеры'));
  check('хаб: плитка в списке работ', !!byText(w, '.tile-row', 'Плитка'));
  check('хаб: «Добавить работу» есть', !!byText(w, '.btn', 'Добавить работу'));
  byText(w, '.tile-row', 'Плитка').click();
  await wait(80);
  check('холст: число плиток', t().includes('145'));
  check('холст: схема запрошена', calls.some((c) => /scheme\/0\.png/.test(c.url)));
  check('спека: раскладка есть', !!byText(w, '.seg button', 'Диагональ'));
  check('спека: степпер шва есть', !!byText(w, '.spec-row .lab', 'Шов'));
  check('шов: и −, и + на месте', w.document.querySelectorAll('.stepper .minus').length >= 1 && w.document.querySelectorAll('.stepper .plus').length >= 1);
  check('спека: эконом-тумблер есть', !!byText(w, '.spec-row', 'Эконом'));
  check('спека: размер плитки есть', !!byText(w, '.spec-row .lab', 'Размер плитки'));

  console.log('\nЖивой пересчёт (тап по раскладке)');
  const before = calls.length;
  byText(w, '.seg button', 'Диагональ').click();
  await wait(200); // debounce 120мс + ответ
  const patch = calls.find((c) => c.m === 'PATCH' && c.body?.pattern === 'diagonal');
  check('тап шлёт PATCH pattern=diagonal', !!patch);
  check('число обновилось после пересчёта', t().includes('150'), t().slice(0, 80));
  void before;

  console.log('\nШов: степпер и ввод с клавиатуры');
  const plus = [...w.document.querySelectorAll('.spec-row')].find((r) => r.textContent.includes('Шов'))?.querySelector('.plus');
  plus?.click();
  await wait(200);
  check('«+» шва шлёт PATCH joint_mm', calls.some((c) => c.m === 'PATCH' && c.body?.joint_mm != null));
  // тап по числу → поле ввода
  const cur = [...w.document.querySelectorAll('.spec-row')].find((r) => r.textContent.includes('Шов'))?.querySelector('.cur');
  cur?.click();
  await wait(30);
  check('тап по числу открывает ввод с клавиатуры', !!w.document.querySelector('.cur-input'));

  console.log('\nВьюер схемы');
  w.document.querySelector('.scheme').click();
  await wait(30);
  check('тап по схеме открывает вьюер', !!w.document.querySelector('.viewer'));
  check('во вьюере есть «Скачать»', !!byText(w, '.viewer button', 'Скачать'));
  w.document.querySelector('.viewer .close').click();
  await wait(20);
  check('вьюер закрывается', !w.document.querySelector('.viewer'));

  console.log('\nСоздание объекта — один экран, «Посчитать»');
  const c2 = makeApp();
  await wait();
  byText(c2.w, '.btn', 'Новый объект').click();
  await wait(50);
  check('быстрый ввод — один экран', c2.w.document.body.textContent.includes('Название объекта') &&
    c2.w.document.body.textContent.includes('Стены по кругу') && !!byText(c2.w, '.btn', 'Посчитать'),
    'ожидал одну форму с полями и «Посчитать»');
  check('тонкая настройка свёрнута с итогом', c2.w.document.body.textContent.includes('проставлено'));
  // заполняем поля по порядку: название, стены, высота, плитка
  const inputs = () => [...c2.w.document.querySelectorAll('#form input')];
  const setIn = (i, val) => { const el = inputs()[i]; el.value = val; el.dispatchEvent(new c2.w.Event('input')); };
  setIn(0, 'Ванная тест'); setIn(1, '2 1.8 2 1.8'); setIn(2, '2.7'); setIn(3, '60 30');
  byText(c2.w, '.btn', 'Посчитать').click();
  await wait(150);
  check('объект СОЗДАН (POST /room)', c2.calls.some((c) => /\/room$/.test(c.url) && c.m === 'POST'),
    'нажал «Посчитать» — объект не создался');
  check('перешёл на хаб объекта', c2.w.document.body.textContent.includes('Работы') && c2.calls.some((c) => /\/api\/objects\/1$/.test(c.url)), c2.w.document.body.textContent.slice(0, 120));
  check('размер «60 30» ушёл в measure', c2.calls.some((c) => /\/measure$/.test(c.url) && c.body?.text === '60 30'));

  console.log('\nВиды работ: добавить ламинат, живой пересчёт, удалить');
  const cw = makeApp();
  await wait();
  byText(cw.w, '.tile-row', 'Ванная').click(); await wait(80);
  byText(cw.w, '.btn', 'Добавить работу').click(); await wait(50);
  check('выбор вида: 6 карточек', cw.w.document.querySelectorAll('#types .tile-row').length === 6);
  byText(cw.w, '.tile-row', 'Ламинат').click(); await wait(120);
  check('экран вида: ламинат создан (POST works)', cw.calls.some((c) => /\/works$/.test(c.url) && c.m === 'POST'));
  check('экран вида: работа и результат', cw.w.document.body.textContent.includes('Ламинат') && cw.w.document.body.textContent.includes('1 764'));
  check('ввод: схема укладки есть', !!byText(cw.w, '.seg button', 'Ёлочка'));
  check('ввод: подложка-тумблер есть', !!byText(cw.w, '.spec-row', 'Подложка'));
  // выключить подложку → PATCH и пересчёт
  byText(cw.w, '.spec-row', 'Подложка').querySelector('.toggle').click();
  await wait(200);
  check('тумблер шлёт PATCH input', cw.calls.some((c) => /\/works\/10$/.test(c.url) && c.m === 'PATCH'));
  // удалить работу
  cw.w.confirm = () => true;
  cw.w.document.querySelector('#del').click(); await wait(120);
  check('работа удалена (DELETE) → вернулись на хаб', cw.calls.some((c) => /\/works\/10$/.test(c.url) && c.m === 'DELETE') && cw.w.document.body.textContent.includes('Работы'));

  console.log('\nВалидация под полем (не общей плашкой)');
  const c3 = makeApp();
  // сервер вернёт 422 на высоту «270»
  const origFetch = c3.w.fetch;
  c3.w.fetch = async (url, o = {}) => {
    if (/\/measure$/.test(url) && JSON.parse(o.body).kind === 'height') {
      const val = JSON.parse(o.body).text;
      if (parseFloat(val) > 20) return {ok: false, status: 422, json: async () => ({error: 'Похоже, единицы перепутаны — напиши 2.7 или 2700'})};
    }
    return origFetch(url, o);
  };
  await wait();
  byText(c3.w, '.btn', 'Новый объект').click(); await wait(50);
  const setIn3 = (i, val) => { const el = [...c3.w.document.querySelectorAll('#form input')][i]; el.value = val; el.dispatchEvent(new c3.w.Event('input')); };
  setIn3(0, 'Тест'); setIn3(1, '2 1.8 2 1.8'); setIn3(2, '270'); setIn3(3, '60 30');
  byText(c3.w, '.btn', 'Посчитать').click(); await wait(120);
  check('ошибка высоты показана под полем', !!byText(c3.w, '.field .err', 'единицы перепутаны'),
    'ждал .field .err с текстом');
  check('объект НЕ создан при ошибке', !c3.calls.some((c) => /\/room$/.test(c.url)));

  console.log('\nДеньги (баг DocumentFragment: null.value)');
  const c4 = makeApp();
  await wait();
  byText(c4.w, '.tile-row', 'Ванная').click(); await wait(80);
  byText(c4.w, '.btn', 'Деньги').click(); await wait(50);
  c4.w.document.querySelector('#pay').value = '20000';
  byText(c4.w, '.btn', 'Записать приход').click(); await wait(120);
  check('приход записан без ошибки', c4.calls.some((c) => /\/payments$/.test(c.url)) && !c4.errs.length,
    c4.errs[0] || '');
  check('получено обновилось', c4.w.document.body.textContent.includes('20 000'));

  console.log('\nПереименование объекта');
  const c5 = makeApp();
  await wait();
  byText(c5.w, '.tile-row', 'Ванная').click(); await wait(80);
  c5.w.document.querySelector('#title').click(); await wait(20);
  const ti = c5.w.document.querySelector('.title-input');
  check('тап по названию открыл ввод', !!ti);
  if (ti) { ti.value = 'Санузел'; ti.dispatchEvent(new c5.w.Event('blur')); await wait(80); }
  check('переименование ушло на сервер', c5.calls.some((c) => /\/title$/.test(c.url) && c.body?.title === 'Санузел'));

  console.log('\nОбщая смета по объекту (все работы в 1 документ)');
  const ce = makeApp();
  await wait();
  byText(ce.w, '.tile-row', 'Ванная').click(); await wait(80);
  byText(ce.w, '.btn', 'Смета').click(); await wait(80);
  check('смета: обе работы (плитка+ламинат)', ce.w.document.body.textContent.includes('Укладка плитки') && ce.w.document.body.textContent.includes('Укладка ламината'));
  check('смета: общий итог', ce.w.document.body.textContent.includes('63 564'));
  check('смета: материалы обоих видов', ce.w.document.body.textContent.includes('Плитка 600×300') && ce.w.document.body.textContent.includes('Ламинат'));

  console.log('\nВне Telegram (пустой initData)');
  const out = makeApp({initData: ''});
  await wait(40);
  check('показал «Откройте через бота»', out.w.document.body.textContent.includes('Откройте через бота'));
  check('в сервер без initData не стучались', !out.calls.length, `дёрнул ${out.calls.length}`);

  console.log(`\nОшибок в консоли: ${errs.length + out.errs.length}`);
  [...errs, ...out.errs].slice(0, 6).forEach((e) => console.log('  ⚠️ ' + e));
  const bad = failed || errs.length || out.errs.length;
  console.log(bad ? `\n❌ ПРОВАЛОВ: ${failed}` : '\n✅ ВСЁ ПРОШЛО');
  process.exit(bad ? 1 : 0);
})();
