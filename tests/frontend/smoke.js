/* Фронт мини-аппа в jsdom: экраны обязаны отрисоваться, а кнопки — сработать.
 * Сервер поддельный, но отвечает ровно тем, что отдаёт настоящий API. */
const {JSDOM} = require('jsdom');
const fs = require('fs');

const APP = require('path').join(__dirname, '../../src/tilebot/web/static/app.js');

const RESULT = {
  area_m2: 24.12, tiles_grid: 145, cuts_count: 40, walls: 4, has_floor: true,
  can_wrap: true, wrap: false, pattern: 'brick', start_from: 'edge', offset_ratio: 0.5,
  grout: null, grout_kind: 'cement', waste: 0.07, waterproofing: true, tile_locked: false,
  tile_photo: false,
  tile: {width_mm: 600, height_mm: 300, joint_mm: 1.4, joint_text: '1,4',
         thickness_mm: 9, per_pack: 8, price_per_m2: null, lying: true},
  tile_cost: null,
  surfaces: [
    {index: 0, name: 'Стена 1', kind: 'wall', area_m2: 5.4, tiles: 36, cuts: 10,
     tile_w: 600, tile_h: 300, openings: []},
    {index: 1, name: 'Пол', kind: 'floor', area_m2: 3.6, tiles: 13, cuts: 4,
     tile_w: 600, tile_h: 600, openings: []},
  ],
  purchase: [
    {name: 'Плитка 600×300', qty: 131, qty_text: '131', unit: 'шт',
     note: '23.6 м² с запасом 7%, ≈17 уп.', kind: 'tile'},
    {name: 'Плиточный клей', qty: 148, qty_text: '148', unit: 'кг', note: '', kind: 'glue'},
  ],
  advice: ['Раскладка ровная: тонких полосок по краям нет.'],
  savings: null,
};

const PROJECT = {
  id: 1, title: 'Ванная, Борзова', surfaces: 5, photos: 0,
  deal_amount: 50000, paid: 20000, due: 30000,
  payments: [{amount: 20000, comment: 'аванс', at: '2026-07-17T10:00:00'}],
  result: RESULT,
};

const routes = [
  [/\/api\/projects$/, 'GET', () => [PROJECT]],
  [/\/api\/projects\/1$/, 'GET', () => PROJECT],
  [/\/api\/projects\/1$/, 'PATCH', (b) => ({...RESULT, wrap: !!b.wrap,
    savings: b.wrap ? {tiles: 5, packs: 1} : null})],
  [/\/api\/projects$/, 'POST', () => ({id: 1, title: 'Ванная, Борзова'})],
  [/\/api\/projects\/1\/room$/, 'POST', () => RESULT],
  [/\/api\/projects\/1\/estimate$/, 'GET', () => ESTIMATE],
  [/\/api\/me$/, 'GET', () => ({id: 1, name: '', phone: '', price: PRICE})],
  [/\/api\/measure$/, 'POST', (b) => ({values: MEASURED[b.kind]})],
];

const MEASURED = {walls: [2, 1.8, 2, 1.8], height: [2.7], tile: [600, 300], size: [2, 2.7]};
const PRICE = {wall_tiling: 1200, floor_tiling: 1000, cutting: 60, grouting: 200,
  grouting_epoxy: 450, waterproofing: 400, priming: 100, demolition: 500, min_order: 0};
const ESTIMATE = {
  title: 'Ванная, Борзова',
  works: [{name: 'Укладка плитки на стену', qty: 20.5, unit: 'м²', price: 1200,
           total: 24600, total_text: '24 600 ₽'}],
  works_total: 24600, works_total_text: '24 600 ₽',
  materials: [{name: 'Плитка 600×300', qty: 131, qty_text: '131', unit: 'шт',
               note: '', kind: 'tile', cost: 35400, packs: 17}],
  materials_total: 0, rough_materials_total: 35400, rough_total: 60000,
  rough_total_text: '60 000 ₽', grand_total: 24600, grand_total_text: '24 600 ₽', note: '',
  price: PRICE,
};

const calls = [];
const dom = new JSDOM(
  `<!doctype html><body><div id="app"><div class="loading">Загружаю…</div></div></body>`,
  {runScripts: 'outside-only', url: 'https://plitka.example/'},
);
const {window} = dom;

window.Telegram = {WebApp: {
  initData: 'user=%7B%22id%22%3A1%7D&hash=x',
  ready() {}, expand() {},
  BackButton: {show() {}, hide() {}, onClick() {}},
  HapticFeedback: {impactOccurred() {}, notificationOccurred() {}},
  showConfirm(_, cb) { cb(true); },
}};

window.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET';
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push(`${method} ${url}`);
  if (/scheme\/\d+\.png/.test(url)) {
    return {ok: true, status: 200, blob: async () => new window.Blob([1])};
  }
  for (const [re, m, fn] of routes) {
    if (re.test(url.split('?')[0]) && m === method) {
      return {ok: true, status: 200, json: async () => fn(body)};
    }
  }
  throw new Error(`поддельный сервер не знает ${method} ${url}`);
};
window.URL.createObjectURL = () => 'blob:fake';

const errors = [];
window.addEventListener('error', (e) => errors.push(e.error?.message || e.message));
window.eval(fs.readFileSync(APP, 'utf8'));

const text = () => window.document.body.textContent.replace(/\s+/g, ' ');
const q = (sel) => window.document.querySelector(sel);
const byLabel = (t) => [...window.document.querySelectorAll('button')]
  .find((b) => b.textContent.includes(t));

const wait = () => new Promise((r) => setTimeout(r, 30));
let failed = 0;
const check = (name, cond, extra = '') => {
  if (cond) return console.log(`  ✅ ${name}`);
  failed++;
  console.log(`  ❌ ${name}${extra ? ' — ' + extra : ''}`);
};

(async () => {
  await wait();

  console.log('\nСписок объектов');
  check('объект показан', text().includes('Ванная, Борзова'));
  check('долг заказчика виден', text().includes('30 000 ₽'), text().slice(0, 120));

  console.log('\nЭкран объекта');
  byLabel('Ванная, Борзова').click();
  await wait();
  check('сводка комнаты', text().includes('Комната целиком'));
  check('площадь с сервера', text().includes('24.12 м²'));
  check('закупка с сервера', text().includes('131 шт'));
  check('плитка как легла', text().includes('600×300 (лёжа)'));
  check('шов не округлён до 1', text().includes('шов 1,4 мм'), text().slice(0, 200));
  check('совет показан', text().includes('Раскладка ровная'));
  check('схема запрошена', calls.some((c) => c.includes('scheme/0.png')));
  check('кнопка эконома есть', !!byLabel('Эконом: по кругу'));

  console.log('\nЭконом');
  byLabel('Эконом: по кругу').click();
  await wait();
  check('PATCH ушёл', calls.includes('PATCH /api/projects/1'));
  check('экономия показана', text().includes('Эконом сберёг 5 плиток'), text().slice(0, 200));
  check('кнопка сменилась', !!byLabel('Вернуть обычную'));

  console.log('\nСмета');
  byLabel('Смета заказчику').click();
  await wait();
  check('работа посчитана', text().includes('24 600 ₽'));
  check('материалы не проданы', text().includes('покупает сам'));
  byLabel('К объекту').click();
  await wait();

  console.log('\nДеньги');
  byLabel('Деньги по объекту').click();
  await wait();
  check('приход виден', text().includes('аванс'));
  byLabel('К объекту').click();
  await wait();

  console.log('\nНовый объект: замеры');
  byLabel('объекты').click();
  await wait();
  byLabel('Новый объект').click();
  await wait();
  check('спросил название', text().includes('Как назовём объект'));

  const type = (v) => { q('input').value = v; };
  type('Ванная, Борзова'); byLabel('Дальше').click(); await wait();
  check('спросил режим', text().includes('Что считаем'));
  byLabel('Комната целиком').click(); await wait();
  check('спросил стены', text().includes('по кругу'));
  type('2 1.8 2 1.8'); byLabel('Дальше').click(); await wait();
  check('стены разобрал сервер', calls.includes('POST /api/measure'));
  check('спросил высоту', text().includes('Высота стен'), text().slice(0, 100));
  type('2.7'); byLabel('Дальше').click(); await wait();
  check('спросил про пол', text().includes('Пол тоже плиткой'), text().slice(0, 100));
  byLabel('Да, и пол').click(); await wait();
  type('60 30'); byLabel('Дальше').click(); await wait();
  check('спросил шов', text().includes('Какой шов'), text().slice(0, 100));
  byLabel('1,5').click(); await wait();
  check('спросил толщину', text().includes('Толщина'), text().slice(0, 100));
  byLabel('9').click(); await wait();
  check('спросил упаковку', text().includes('в упаковке'), text().slice(0, 100));
  type('8'); byLabel('Дальше').click(); await wait();
  check('спросил плитку на пол', text().includes('на пол'), text().slice(0, 100));
  byLabel('Пропустить').click(); await wait();
  check('спросил раскладку', text().includes('Раскладка'), text().slice(0, 100));
  byLabel('Вразбежку').click(); await wait();
  check('спросил начало ряда', text().includes('Откуда начинаем'), text().slice(0, 100));
  byLabel('реши сам').click(); await wait();
  check('спросил запас', text().includes('Запас'), text().slice(0, 100));
  byLabel('7').click(); await wait();
  check('спросил гидроизоляцию', text().includes('Гидроизоляция'), text().slice(0, 100));
  byLabel('Да, мокрая зона').click(); await wait();
  check('комната ушла на сервер', calls.includes('POST /api/projects/1/room'));
  check('показал результат', text().includes('Купить'), text().slice(0, 150));

  console.log('\nПрайс');
  byLabel('объекты').click(); await wait();
  byLabel('Прайс').click(); await wait();
  check('прайс открылся', text().includes('Укладка на стену'), text().slice(0, 100));

  console.log(`\nОшибок в консоли: ${errors.length}`);
  errors.forEach((e) => console.log('  ⚠️ ' + e));
  console.log(failed ? `\n❌ ПРОВАЛОВ: ${failed}` : '\n✅ ВСЁ ПРОШЛО');
  process.exit(failed || errors.length ? 1 : 0);
})();
