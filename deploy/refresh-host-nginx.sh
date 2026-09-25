#!/bin/sh
# Keep Ubuntu host nginx (127.0.0.1:30080) connected to the in-cluster frontend.
# Minikube docker-driver NodePort is NOT on localhost — without this forward you get 502.
set -eu

NAMESPACE="${KUBE_NAMESPACE:-ml-service}"
LISTEN="${AV_FORWARD_PORT:-30080}"
UNIT="av-nginx-forward.service"
KUBECTL="$(command -v kubectl)"
LOG="/tmp/av-nginx-forward.log"

if [ -z "$KUBECTL" ]; then
  echo "kubectl not found" >&2
  exit 1
fi

stop_old_forward() {
  pkill -f "kubectl port-forward.*agri-nginx-service" 2>/dev/null || true
  pkill -f "minikube kubectl -- port-forward.*agri-nginx-service" 2>/dev/null || true
}

start_forward() {
  stop_old_forward
  # New session so GitLab does not kill this with the job process group.
  setsid "$KUBECTL" port-forward \
    -n "$NAMESPACE" \
    --address 127.0.0.1 \
    svc/agri-nginx-service "${LISTEN}:80" \
    </dev/null >"$LOG" 2>&1 &
  sleep 2
}

install_systemd() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  if [ "$(id -u)" -eq 0 ]; then
    dest="/etc/systemd/system/${UNIT}"
    ctl="systemctl"
  elif [ -d /run/user/"$(id -u)"/systemd ] || systemctl --user show-environment >/dev/null 2>&1; then
    mkdir -p "${HOME}/.config/systemd/user"
    dest="${HOME}/.config/systemd/user/${UNIT}"
    ctl="systemctl --user"
  else
    return 1
  fi

  cat >"$dest.tmp" <<EOF
[Unit]
Description=Agriculture Vision nginx port-forward
After=network.target

[Service]
Type=simple
Restart=always
RestartSec=3
ExecStart=${KUBECTL} port-forward -n ${NAMESPACE} --address 127.0.0.1 svc/agri-nginx-service ${LISTEN}:80

[Install]
WantedBy=default.target
EOF
  if [ "$(id -u)" -eq 0 ]; then
    mv "$dest.tmp" "$dest"
  else
    mv "$dest.tmp" "$dest"
  fi
  $ctl daemon-reload
  $ctl enable --now "$UNIT" || $ctl restart "$UNIT"
}

maybe_reload_host_nginx() {
  if ! command -v nginx >/dev/null 2>&1; then
    return 0
  fi
  SUDO=""
  if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || return 0
    SUDO="sudo"
  fi
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 512m;
    location / {
        proxy_pass http://127.0.0.1:${LISTEN};
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
    $SUDO cp "$tmp" /etc/nginx/sites-available/agriculture-vision
    $SUDO ln -sfn /etc/nginx/sites-available/agriculture-vision /etc/nginx/sites-enabled/agriculture-vision
    $SUDO rm -f /etc/nginx/sites-enabled/default
  elif [ -d /etc/nginx/conf.d ]; then
    $SUDO cp "$tmp" /etc/nginx/conf.d/agriculture-vision.conf
  else
    rm -f "$tmp"
    return 0
  fi
  rm -f "$tmp"
  $SUDO nginx -t && ($SUDO nginx -s reload 2>/dev/null || $SUDO systemctl reload nginx)
}

install_systemd || true
maybe_reload_host_nginx || echo "host nginx not updated (need root); will use 127.0.0.1:${LISTEN}"

if ! curl -sfI "http://127.0.0.1:${LISTEN}/" >/dev/null 2>&1; then
  start_forward
fi

for i in 1 2 3 4 5 6 7 8; do
  if curl -sfI "http://127.0.0.1:${LISTEN}/" >/dev/null; then
    echo "localhost:${LISTEN} is serving the frontend"
    exit 0
  fi
  sleep 1
done
echo "WARNING: 127.0.0.1:${LISTEN} not responding yet (see ${LOG})" >&2
exit 0
