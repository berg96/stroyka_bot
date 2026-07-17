# Выкладка мини-аппа

Бот от этого не меняется: мини-апп — отдельный сервис на том же коде и той же
базе. Не выложили — бот работает как работал, просто в меню нет кнопки
«📱 Приложение».

## Что нужно один раз

1. **Поддомен.** По образцу остальных на UK — FreeDNS (afraid.org), запись A на
   `82.26.193.24`. Дальше по тексту `plitka.mooo.com` — заменить на выбранный.

2. **SNI-демукс.** В `/etc/nginx/nginx.conf`, в `map $ssl_preread_server_name
   $backend_443`, рядом с остальными:

   ```
   plitka.mooo.com  127.0.0.1:8443;
   ```

3. **Конфиги nginx и сертификат:**

   ```bash
   cp deploy/stroyka-http.conf  /etc/nginx/conf.d/
   nginx -t && systemctl reload nginx
   certbot certonly --webroot -w /var/www/html -d plitka.mooo.com
   cp deploy/stroyka-https.conf /etc/nginx/conf.d/
   nginx -t && systemctl reload nginx
   ```

   Порядок важен: `stroyka-https.conf` ссылается на сертификат, которого до
   certbot ещё нет, и nginx с ним не стартует.

4. **Адрес — в `.env`**, иначе кнопки в боте не будет (Telegram принимает в
   WebAppInfo только https, и кнопку с пустым адресом он не проглотит):

   ```
   WEBAPP_URL=https://plitka.mooo.com
   ```

5. **Сервис:**

   ```bash
   cp deploy/stroyka-web.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now stroyka-web
   systemctl restart stroyka-bot   # чтобы бот перечитал WEBAPP_URL
   ```

   `enable`, а не только `start`: без него после ребута сервис не поднимется —
   на этом уже обжигались с ботом.

## Проверить

```bash
systemctl status stroyka-web --no-pager
curl -s -o /dev/null -w '%{http_code}\n' https://plitka.mooo.com/        # 200
curl -s https://plitka.mooo.com/api/projects                             # 401 — так и надо
```

`401` без initData — это правильно: мини-апп пускает только по подписи Telegram.

## Откатить

```bash
systemctl disable --now stroyka-web
rm /etc/nginx/conf.d/stroyka-{http,https}.conf && nginx -t && systemctl reload nginx
```

Плюс убрать `WEBAPP_URL` из `.env` и перезапустить бота — кнопка исчезнет.
Данные при этом целы: мини-апп ничего своего не хранит, всё в той же базе бота.
