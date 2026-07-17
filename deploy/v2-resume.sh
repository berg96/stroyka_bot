#!/usr/bin/env bash
# Одноразовое продолжение верстки v2 после сброса 5-часового лимита.
# Запускается transient systemd-таймером (см. конец файла — как ставился).
# Поднимает headless-сессию claude в /root/stroyka-bot и даёт ей план из
# docs/v2-progress.md. Всё логируется; бэкенд и прод-боты не трогаются.
set -uo pipefail
cd /root/stroyka-bot || exit 1
LOG=/root/stroyka-bot/logs/v2-resume.$(date +%Y%m%d-%H%M).log
mkdir -p logs

read -r -d '' PROMPT <<'EOF'
Ты Claude Code на сервере UK. Заверши редизайн v2 фронта мини-аппа плиточника.
Рабочая папка /root/stroyka-bot. СНАЧАЛА прочитай docs/v2-progress.md — там полный
план и источники (макет в /root/agent-second-brain/vault/attachments/2026-07-17/
Плиточник_MiniApp_dc_1-200120.html, бриф docs/design-miniapp-brief.md). Файлы v2
(static/index.html, static/app.css, static/app.js) уже написаны и закоммичены, но
не полностью проверены; базовый рендер в jsdom проходит.

Задачи:
1. Обнови tests/frontend/smoke.js под DOM v2 (холст-SPA): портфель -> открытие
   холста, живой пересчёт (тап по сегменту «Диагональ» в спеке шлёт PATCH
   pattern=diagonal и обновляет число «Купить»), экран «вне Telegram» при пустом
   initData. Прогон: cd tests/frontend && node smoke.js
2. uv run pytest -q (API не менялся — ждём зелёное) и uv run ruff check .
3. Почини всплывшие баги. Особое внимание — функция wrapCtl в app.js (кривовата):
   спека холста должна корректно рисовать сегменты (раскладка, смещение только для
   brick, начало ряда, вид затирки), чипы цвета затирки, степперы шва и запаса,
   тумблеры эконома (только can_wrap) и гидроизоляции; тап по контролу -> livePatch.
4. ВАЖНО: v2 УЖЕ живёт на https://plitka.mooo.com (StaticFiles отдаёт с диска).
   Если smoke удалось довести до зелёного — просто закоммить и запушь, v2 остаётся
   живой. Если НЕ можешь довести до зелёного за разумное время — откати три
   статик-файла на v1 (git log; v1 рабочий) и закоммить откат, чтобы живая версия
   не была сломанной, оставь заметку в docs/v2-progress.md.
5. НЕ трогай бэкенд/API (src/tilebot/web/app.py и др.). НЕ шли ничего Сане/в
   Telegram. Обнови docs/v2-progress.md статусом и коммить по ходу.
Работай аккуратно.
EOF

echo "=== v2-resume $(date -u) ===" | tee -a "$LOG"
/root/.local/bin/claude --print --dangerously-skip-permissions "$PROMPT" >>"$LOG" 2>&1
echo "=== готово $(date -u), rc=$? ===" | tee -a "$LOG"
