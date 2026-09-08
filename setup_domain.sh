#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${AIOFF_DOMAIN:-aioff-ai.duckdns.org}"
UPSTREAM="127.0.0.1:3000"
NGINX_SITE="/etc/nginx/sites-available/aioff"

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash setup_domain.sh)"
  exit 1
fi

cd /opt/aioff

echo "[1/6] Check AI OFF service"
curl -fsS "http://${UPSTREAM}/health" >/dev/null

echo "[2/6] Install nginx + certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

echo "[3/6] Configure reverse proxy: ${DOMAIN} -> ${UPSTREAM}"
cat > "${NGINX_SITE}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://${UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # AI chat/stream responses must not be buffered by nginx.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF

ln -sfn "${NGINX_SITE}" /etc/nginx/sites-enabled/aioff
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null
systemctl restart nginx

echo "[4/6] Verify HTTP routing"
curl -fsS "http://${DOMAIN}/health"
echo

echo "[5/6] Issue HTTPS certificate and redirect HTTP -> HTTPS"
certbot --nginx \
  -d "${DOMAIN}" \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --redirect

echo "[6/6] Verify HTTPS"
curl -fsS "https://${DOMAIN}/health"
echo

echo "DOMAIN SETUP OK"
echo "URL: https://${DOMAIN}/"
