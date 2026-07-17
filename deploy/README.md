# Выкладка мини-аппа

Бот от этого не меняется: мини-апп — отдельный сервис на том же коде и той же
базе. Не выложили — бот работает как работал, просто в меню нет кнопки
«📱 Приложение».

Адрес: **plitka.mooo.com** (A-запись → `82.26.193.24` заведена на afraid.org).

## Довести до рабочего https

На UK (`82.26.193.24`), когда `plitka.mooo.com` начал резолвиться сюда:

```bash
cd /root/stroyka-bot
./deploy/finalize.sh plitka.mooo.com
```

Скрипт (идемпотентный, любой сбой — стоп):

1. ждёт, пока DNS реально резолвится в наш IP;
2. выпускает сертификат Let's Encrypt (webroot);
3. ставит nginx: `:80` редирект + `:8443` TLS → uvicorn `:8110`;
4. добавляет домен в SNI-роутер `:443` (с бэкапом `nginx.conf`);
5. пишет `WEBAPP_URL` в `.env`, поднимает `stroyka-web`, рестартует бота —
   кнопка «📱 Приложение» оживает.

В конце сам проверит: `GET /` → 200, `GET /api/projects` без подписи → 401.

## Запасной путь — duckdns

Если afraid.org недоступен, тот же скрипт умеет duckdns: создать поддомен на
https://www.duckdns.org (вход по OAuth, без капчи), скопировать токен и

```bash
./deploy/finalize.sh <поддомен>.duckdns.org <токен>
```

Тогда скрипт сам выставит A-запись на наш IP (duckdns при создании пишет IP
браузера, а не сервера) и дальше по тем же шагам.

## Проверить руками

```bash
systemctl status stroyka-web --no-pager
curl -s -o /dev/null -w '%{http_code}\n' https://plitka.mooo.com/          # 200
curl -s https://plitka.mooo.com/api/projects                               # 401 — так и надо
```

`401` без initData — правильно: мини-апп пускает только по подписи Telegram.

## Откатить

```bash
systemctl disable --now stroyka-web
rm /etc/nginx/conf.d/stroyka-{http,https}.conf
# убрать строку plitka.mooo.com из map $ssl_preread_server_name в /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
sed -i '/^WEBAPP_URL=/d' /root/stroyka-bot/.env && systemctl restart stroyka-bot
```

Кнопка исчезнет, данные целы: мини-апп своего не хранит, всё в той же базе бота.
