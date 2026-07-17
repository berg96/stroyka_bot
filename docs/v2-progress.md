# Редизайн мини-аппа v2 — прогресс и как продолжить

**Статус на 2026-07-17 20:13 BST:** в работе. Верстаю v2 фронта по макету дизайнера.

## Что делаем
Переверстка фронта мини-аппа под макет Claude Design: модель «объект — живой холст»
(схема-герой + правка любого параметра на месте с мгновенным пересчётом), а не визард.
**Бэкенд/API НЕ трогаем** — он готов. Решение Артёма по теме: **вариант A** — привязать
к теме клиента Telegram (`--tg-theme-*`), палитра дизайнера как фолбэк, оранжевый акцент
поверх.

## Источники правды
- **Макет:** `/root/agent-second-brain/vault/attachments/2026-07-17/Плиточник_MiniApp_dc_1-200120.html`
  (self-contained HTML, инлайн-стили, 90 SVG-иконок; палитра: светлая тёплая
  #f4f2ef/#e9e7e3/#0d0d0d/#8a8f98, тёмная телеграмная #0e1621/#232e3c/#7f91a4, акцент
  #ea580c / нажат #c2410c). Копия в скретчпаде `mockup.html`.
- **Бриф:** `docs/design-miniapp-brief.md` — все 6 экранов, состояния, ветвления, API.
- **Форма данных API:** `_result_json` в `src/tilebot/web/app.py` (см. бриф раздел 5.3).

## Сделано
- ✅ `src/tilebot/web/static/app.css` — v2 переписан: токен-слой на `--tg-theme-*` +
  фолбэки (свет/тьма), компоненты холста (scheme-hero, tabs, result, kpis, spec-row,
  stepper, toggle, chips), состояния (skeleton/center/error), табличные цифры. Закоммичен.

## Осталось (порядок)
1. **`src/tilebot/web/static/index.html`** — минимальный (грузит app.css/app.js,
   telegram-web-app.js). v1 подойдёт почти как есть.
2. **`src/tilebot/web/static/app.js`** — ПОЛНАЯ переверстка под холст-SPA:
   - Экраны: `list` (портфель), `create` (быстрый ввод: имя → режим → стены/высота или
     стена+размер → плитка → «Посчитать»; тонкая настройка свёрнута с дефолтами),
     `canvas` (ГЕРОЙ), `estimate`/`act`, `money`, `price`.
   - **Холст:** схема-PNG сверху (`/api/projects/{id}/scheme/{index}.png`, грузить
     blob'ом с заголовком X-Init-Data — см. `loadScheme` в старом app.js из git),
     табы-миниатюры поверхностей (свайп/тап — **НЕ PATCH**, читаем
     `result.surfaces[index]`), карточка результата (большое «Купить N», kpi упаковки/
     резать), спека с живой правкой.
   - **Живой пересчёт (ядро):** тап по контролу → оптимистично меняем контрол + haptic
     → состояние «считаю» (scheme `.computing` opacity, числа `.computing-dim`) →
     debounce ~120мс, один запрос в полёте, **версия запроса** (игнорить устаревший
     ответ) → `PATCH /api/projects/{id} {поле}` → новый result → кроссфейд схемы + fade
     чисел + haptic success. НЕ звать `run()` изнутри `run()` (баг v1 — вложенный
     глотался; см. коммит про мёртвую кнопку). Отдельный `patchLive()` с дебаунсом.
   - PATCH-поля: `pattern, start_from, offset_label(1/2|1/3|1/4), waste, grout,
     grout_kind, wrap, waterproofing, rotate, tile_size{width_mm,height_mm,kind},
     tile_price`; проём — `POST /opening {surface_id,name,width_m,height_m}`.
   - Видимость: эконом (`wrap`) — только `can_wrap=true`; смещение — только
     `pattern==brick`.
   - Состояния: skeleton при загрузке, пусто (нет объектов / нет поверхностей), ошибка +
     «Повторить», вне Telegram (пустой initData → экран «Откройте через бота»,
     в сервер НЕ стучимся), валидация ввода у поля.
   - Разбор ввода — сервером: `POST /api/measure {kind:walls|height|tile|size, text}`.
   - Смета/акт: `GET /estimate|/act`; смета — материалы НЕ суммируются с работой
     («ВСЁ ВМЕСТЕ ≈»), акт — «ИТОГО К ОПЛАТЕ».
   - Иконки: инлайн SVG Lucide-стиля через `icon(name)`-хелпер (без эмодзи).
   - Кнопка меню/навигация: Telegram BackButton; главное действие — MainButton, где
     уместно (иначе `.dock`-кнопка).
3. **`tests/frontend/smoke.js`** — обновить под новый DOM (портфель→холст, живой
   пересчёт через PATCH, состояние вне-Telegram). Прогон: `cd tests/frontend && node smoke.js`.
4. **Python-тесты**: `uv run pytest -q` (API не менялся — должны быть зелёными, 196).
   Ruff: `uv run ruff check .`.
5. **Деплой:** `systemctl restart stroyka-web` (StaticFiles отдаёт с диска), проверить
   `curl -s https://plitka.mooo.com/ | grep title` и `/api/projects` без подписи → 401.
6. **Коммит + пуш.** Хэндофф `vault/.session/handoffs/stroyka-bot.md` обновить.

## Проверка (обязательно — фронт тестами не виден)
Прогнать `tests/frontend/smoke.js` в jsdom (Node 18 + `jsdom@22` в `tests/frontend/`):
экраны рисуются, живой пересчёт шлёт PATCH и обновляет числа, вне-Telegram-экран, в
сервер без initData не стучимся. v1 так поймал мёртвую кнопку — не пропускать.

## Не потерять
- v1 остаётся в проде до готовности v2; не ломать API-контракт.
- Сане ничего не слать без явного «да» Артёма.
