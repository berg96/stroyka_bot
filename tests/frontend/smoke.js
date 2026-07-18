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
  console.log('Портфель → холст');
  const {w, calls, errs} = makeApp();
  await wait();
  check('список рисуется', w.document.body.textContent.includes('Ванная, Борзова'));
  byText(w, '.tile-row', 'Ванная').click();
  await wait(80);
  const t = () => w.document.body.textContent;
  check('холст: число плиток', t().includes('145'));
  check('холст: схема запрошена', calls.some((c) => /scheme\/0\.png/.test(c.url)));
  check('спека: раскладка есть', !!byText(w, '.seg button', 'Диагональ'));
  check('спека: степпер шва есть', !!byText(w, '.spec-row .lab', 'Шов'));
  check('шов: и −, и + на месте', w.document.querySelectorAll('.stepper .minus').length >= 1 && w.document.querySelectorAll('.stepper .plus').length >= 1);
  check('спека: эконом-тумблер есть', !!byText(w, '.spec-row', 'Эконом'));

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
