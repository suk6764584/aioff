#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${AIOFF_DOMAIN:-aioff-ai.duckdns.org}"
UPSTREAM="127.0.0.1:3000"

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash setup_domain.sh)"
  exit 1
fi

cd /opt/aioff

echo "[1/6] Check AI OFF service"
curl -fsS "http://${UPSTREAM}/health" >/dev/null

echo "[2/6] Install nginx + certbot"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y nginx certbot python3-certbot-nginx
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y nginx
  if ! dnf install -y certbot python3-certbot-nginx; then
    dnf install -y epel-release
    dnf install -y certbot python3-certbot-nginx
  fi
elif command -v yum >/dev/null 2>&1; then
  yum install -y nginx
  if ! yum install -y certbot python3-certbot-nginx; then
    yum install -y epel-release
    yum install -y certbot python3-certbot-nginx
  fi
else
  echo "ERROR: supported package manager not found (apt-get/dnf/yum)"
  exit 1
fi

if [ -d /etc/nginx/sites-available ]; then
  NGINX_SITE="/etc/nginx/sites-available/aioff"
else
  NGINX_SITE="/etc/nginx/conf.d/aioff.conf"
fi

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

if [ -d /etc/nginx/sites-enabled ]; then
  ln -sfn "${NGINX_SITE}" /etc/nginx/sites-enabled/aioff
  rm -f /etc/nginx/sites-enabled/default
fi

# RHEL-family SELinux can block nginx -> localhost:3000 proxying.
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = "Enforcing" ]; then
  if command -v setsebool >/dev/null 2>&1; then
    setsebool -P httpd_can_network_connect 1
  else
    echo "WARN: SELinux is Enforcing but setsebool is unavailable."
  fi
fi

nginx -t
systemctl enable nginx >/dev/null
systemctl restart nginx

# Open the local OS firewall when firewalld is running.
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http >/dev/null
  firewall-cmd --permanent --add-service=https >/dev/null
  firewall-cmd --reload >/dev/null
fi

echo "[4/6] Verify HTTP routing"
curl -fsS -H "Host: ${DOMAIN}" http://127.0.0.1/health
echo

echo "[5/6] Issue HTTPS certificate and redirect HTTP -> HTTPS"
certbot --nginx \
  -d "${DOMAIN}" \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --redirect

echo "[6/6] Verify HTTPS"
curl -fsS --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/health"
echo

echo "DOMAIN SETUP OK"
echo "URL: https://${DOMAIN}/"
