# Выкладка мини-аппа

Бот от этого не меняется: мини-апп — отдельный сервис на том же коде и той же
базе. Не выложили — бот работает как работал, просто в меню нет кнопки
«📱 Приложение».

Адрес — на **duckdns** (afraid.org капчит создание поддоменов и был недоступен).

## Шаг вручную (1 минута)

1. Зайти на https://www.duckdns.org — вход через GitHub/Google, паролей заводить
   не надо.
2. В поле **sub domain** вписать имя (напр. `plitka-bot`) → **add domain**.
   Какой IP там подставился — неважно, скрипт всё равно перезапишет на наш.
3. Скопировать **token** (вверху страницы) — длинная строка.

## Остальное — одним прогоном

На UK (`82.26.193.24`):

```bash
cd /root/stroyka-bot
./deploy/finalize_duckdns.sh <поддомен> <токен>
# например: ./deploy/finalize_duckdns.sh plitka-bot 46e1b2c3-...
```

Скрипт (идемпотентный, любой сбой — стоп):

1. ставит A-запись `<поддомен>.duckdns.org` → `82.26.193.24` по токену
   (duckdns при создании пишет IP браузера, а не сервера — без этого ведёт мимо);
2. ждёт, пока DNS реально начнёт резолвиться сюда;
3. выпускает сертификат Let's Encrypt (webroot);
4. ставит nginx: `:80` редирект + `:8443` TLS → uvicorn `:8110`;
5. добавляет поддомен в SNI-роутер `:443` (с бэкапом `nginx.conf`);
6. пишет `WEBAPP_URL` в `.env`, поднимает `stroyka-web`, рестартует бота —
   кнопка «📱 Приложение» оживает;
7. складывает токен в `.env` (сервер статичный, но пусть IP можно освежать).

В конце сам проверит: `GET /` → 200, `GET /api/projects` без подписи → 401.

## Проверить руками

```bash
systemctl status stroyka-web --no-pager
curl -s -o /dev/null -w '%{http_code}\n' https://<поддомен>.duckdns.org/         # 200
curl -s https://<поддомен>.duckdns.org/api/projects                              # 401 — так и надо
```

`401` без initData — правильно: мини-апп пускает только по подписи Telegram.

## Откатить

```bash
systemctl disable --now stroyka-web
rm /etc/nginx/conf.d/stroyka-{http,https}.conf
# убрать строку поддомена из map $ssl_preread_server_name в /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
sed -i '/^WEBAPP_URL=/d' /root/stroyka-bot/.env && systemctl restart stroyka-bot
```

Кнопка исчезнет, данные целы: мини-апп своего не хранит, всё в той же базе бота.
