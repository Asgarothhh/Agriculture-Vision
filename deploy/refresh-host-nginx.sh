#!/bin/sh
# Point the Ubuntu host nginx at the current minikube NodePort.
# Minikube IP changes after delete/restart; a stale proxy_pass is a 502.
set -eu

if ! command -v nginx >/dev/null 2>&1; then
  echo "host nginx not installed, skip reverse-proxy refresh"
  exit 0
fi
if ! command -v minikube >/dev/null 2>&1; then
  echo "minikube not found, skip reverse-proxy refresh"
  exit 0
fi

IP="$(minikube ip)"
PORT="${AV_NODEPORT:-30080}"
echo "Refreshing host nginx upstream → http://${IP}:${PORT}"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "need root to update host nginx, skip"
    exit 0
  fi
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 512m;
    location / {
        proxy_pass http://${IP}:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 10s;
    }
}
EOF

if [ -d /etc/nginx/sites-available ]; then
  dest="/etc/nginx/sites-available/agriculture-vision"
  $SUDO cp "$tmp" "$dest"
  $SUDO ln -sfn "$dest" /etc/nginx/sites-enabled/agriculture-vision
  $SUDO rm -f /etc/nginx/sites-enabled/default
elif [ -d /etc/nginx/conf.d ]; then
  dest="/etc/nginx/conf.d/agriculture-vision.conf"
  $SUDO cp "$tmp" "$dest"
else
  echo "unknown host nginx layout, skip"
  exit 0
fi

if $SUDO nginx -t; then
  $SUDO nginx -s reload 2>/dev/null || $SUDO systemctl reload nginx
  echo "host nginx reloaded → ${IP}:${PORT}"
else
  echo "host nginx -t failed" >&2
  exit 1
fi
