#!/usr/bin/env bash
# Довести мини-апп до рабочего https — одним прогоном.
#
#   ./finalize.sh <домен> [duckdns-токен]
#   ./finalize.sh plitka.mooo.com                 # afraid.org: A-запись уже стоит
#   ./finalize.sh plitka-bot.duckdns.org <токен>  # duckdns: IP выставит скрипт
#
# Что делает (всё идемпотентно, любой сбой — стоп, живой конфиг вслепую не трогаем):
#   0) если дали duckdns-токен — выставляет A-запись на наш IP (duckdns при
#      создании пишет IP браузера, не сервера);
#   1) ждёт, пока DNS реально начнёт резолвиться в наш IP;
#   2) выпускает сертификат Let's Encrypt (webroot);
#   3) ставит nginx: :80 (редирект) + :8443 TLS → uvicorn :8110;
#   4) добавляет домен в SNI-роутер :443 (с бэкапом nginx.conf);
#   5) прописывает WEBAPP_URL в .env, поднимает сервис, рестартует бота — кнопка
#      «📱 Приложение» оживает.
set -euo pipefail

DOMAIN="${1:?нужен домен, напр. plitka.mooo.com}"
TOKEN="${2:-}"
IP=82.26.193.24
BACKEND=127.0.0.1:8443
PORT=8110
REPO=/root/stroyka-bot
EMAIL=chigar2010@gmail.com

if [ -n "$TOKEN" ]; then
  SUB="${DOMAIN%%.duckdns.org}"
  echo "== duckdns: ставлю A-запись $DOMAIN → $IP =="
  resp=$(curl -sS "https://www.duckdns.org/update?domains=${SUB}&token=${TOKEN}&ip=${IP}")
  [ "$resp" = "OK" ] || { echo "duckdns ответил '$resp' (не OK). Проверь имя и токен."; exit 1; }
fi

echo "== жду, пока DNS начнёт резолвиться сюда =="
for i in $(seq 1 30); do
  got=$(dig +short "$DOMAIN" @1.1.1.1 | tail -1)
  [ "$got" = "$IP" ] && { echo "  резолвится: $DOMAIN → $IP"; break; }
  echo "  ещё нет (вижу '${got:-пусто}'), жду 10с… [$i/30]"; sleep 10
done
[ "$(dig +short "$DOMAIN" @1.1.1.1 | tail -1)" = "$IP" ] || { echo "DNS так и не поднялся."; exit 1; }

echo "== nginx: http-vhost для webroot-челленджа =="
cat > /etc/nginx/conf.d/stroyka-http.conf <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
NGINX
nginx -t && systemctl reload nginx

echo "== certbot =="
certbot certonly --webroot -w /var/www/html -d "$DOMAIN" \
  --non-interactive --agree-tos -m "$EMAIL"

echo "== nginx: https-vhost :8443 → uvicorn :$PORT =="
cat > /etc/nginx/conf.d/stroyka-https.conf <<NGINX
server {
    listen 127.0.0.1:8443 ssl proxy_protocol;
    set_real_ip_from 127.0.0.1;
    real_ip_header proxy_protocol;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
}
NGINX

echo "== SNI-роутер :443: добавляю $DOMAIN =="
if ! grep -q "${DOMAIN} .*${BACKEND}" /etc/nginx/nginx.conf; then
  cp /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%Y%m%d-%H%M%S)"
  # вставляем строку сразу после beauty-bianca-dev в stream-map
  sed -i "/beauty-bianca-dev.mooo.com .*127.0.0.1:8444;/a\\        ${DOMAIN}  ${BACKEND};" \
    /etc/nginx/nginx.conf
fi
nginx -t && systemctl reload nginx

echo "== .env: WEBAPP_URL =="
touch "$REPO/.env"
sed -i '/^WEBAPP_URL=/d;/^DUCKDNS_DOMAIN=/d;/^DUCKDNS_TOKEN=/d' "$REPO/.env"
echo "WEBAPP_URL=https://${DOMAIN}" >> "$REPO/.env"
if [ -n "$TOKEN" ]; then
  { echo "DUCKDNS_DOMAIN=${SUB}"; echo "DUCKDNS_TOKEN=${TOKEN}"; } >> "$REPO/.env"
fi

echo "== сервисы (docker compose) =="
# Бот и мини-апп — в контейнерах из одного образа (см. docker-compose.yml).
# up --build поднимает оба атомарно; бот перечитывает свежий WEBAPP_URL при старте.
cd "$REPO"
docker compose up -d --build

echo "== проверка =="
sleep 3
docker compose ps
code=$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/")
echo "GET https://${DOMAIN}/ → HTTP $code (ждём 200)"
auth=$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/api/projects")
echo "GET /api/projects без подписи → HTTP $auth (ждём 401 — так и надо)"

echo "== готово: https://${DOMAIN} =="
