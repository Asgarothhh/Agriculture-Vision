#!/bin/sh
# Ubuntu nginx/1.24 on :80 serves the SPA and proxies /api/ → FastAPI (spec §9–10).
# Live 502 on POST /api/v1/auth/login: host nginx still uses hostname `api:8000`
# (valid only inside k8s). Point /api/ at 127.0.0.1:8000 and keep kubectl port-forward.
set -eu

NAMESPACE="${KUBE_NAMESPACE:-ml-service}"
KUBECTL="$(command -v kubectl || true)"
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$KUBECTL" ]; then
  echo "kubectl not found" >&2
  exit 1
fi

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi
  command -v sudo >/dev/null 2>&1 || return 1
  sudo -n "$@"
}

port_healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:${1}/api/v1/health" >/dev/null 2>&1
}

stop_old_forwards() {
  pkill -f "kubectl port-forward.*svc/api" 2>/dev/null || true
  pkill -f "kubectl port-forward.*agri-api-service" 2>/dev/null || true
  pkill -f "kubectl port-forward.*agri-nginx-service" 2>/dev/null || true
  if command -v systemctl >/dev/null 2>&1; then
    run_sudo systemctl stop agriculture-vision-forward.service 2>/dev/null || true
  fi
  sleep 1
}

start_one_forward() {
  target="$1"
  mapping="$2"
  hostport="${mapping%%:*}"
  if port_healthy "$hostport"; then
    echo "127.0.0.1:${hostport} already healthy, skip forward"
    return 0
  fi
  echo "port-forward 127.0.0.1:${mapping} → ${target}"
  setsid "$KUBECTL" port-forward -n "$NAMESPACE" --address 127.0.0.1 \
    "$target" "$mapping" \
    </dev/null >>"/tmp/av-pf-${hostport}.log" 2>&1 &
}

install_systemd_forward() {
  command -v systemctl >/dev/null 2>&1 || return 1
  run_sudo true || return 1
  kubeconfig="${KUBECONFIG:-$HOME/.kube/config}"
  unit=/etc/systemd/system/agriculture-vision-forward.service
  run_sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=Agriculture-Vision API port-forward (Ubuntu nginx /api/ → FastAPI)
After=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=2
User=$(id -un)
Environment=KUBECONFIG=${kubeconfig}
ExecStart=${KUBECTL} port-forward -n ${NAMESPACE} --address 127.0.0.1 svc/api 8000:8000

[Install]
WantedBy=multi-user.target
EOF
  run_sudo systemctl daemon-reload
  run_sudo systemctl enable agriculture-vision-forward.service
  run_sudo systemctl restart agriculture-vision-forward.service
  echo "systemd agriculture-vision-forward enabled"
}

ensure_api_hosts() {
  run_sudo true || return 1
  if run_sudo grep -qE '^127\.0\.0\.1[[:space:]].*\bapi\b' /etc/hosts; then
    echo "/etc/hosts already maps api → 127.0.0.1"
  else
    echo "127.0.0.1 api" | run_sudo tee -a /etc/hosts >/dev/null
    echo "added 127.0.0.1 api to /etc/hosts"
  fi
}

patch_host_nginx() {
  run_sudo true || return 1
  patched=0
  if [ -f /etc/nginx/nginx.conf ] && run_sudo grep -qE 'api:8000|agrovision_api|pid /tmp/nginx.pid' /etc/nginx/nginx.conf; then
    echo "Replacing /etc/nginx/nginx.conf (had k8s hostname api:8000)"
    run_sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak-av
    run_sudo cp "$ROOT/nginx/ubuntu-nginx.conf" /etc/nginx/nginx.conf
    patched=1
  fi
  for f in /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* /etc/nginx/sites-available/* /etc/nginx/conf.d/*.conf; do
    [ -e "$f" ] || continue
    [ -f "$f" ] || continue
    if run_sudo grep -qE 'api:8000|agrovision_api|\$api_upstream' "$f"; then
      echo "Patching $f: api:8000 → 127.0.0.1:8000"
      run_sudo sed -i.bak-av \
        -e 's/server[[:space:]]\+api:8000/server 127.0.0.1:8000/g' \
        -e 's|http://api:8000|http://127.0.0.1:8000|g' \
        -e 's|http://\$api_upstream|http://127.0.0.1:8000|g' \
        "$f"
      patched=1
    fi
  done
  if [ "$patched" -eq 0 ] && [ -d /etc/nginx/sites-available ]; then
    echo "Installing sites-available/agriculture-vision"
    run_sudo cp "$ROOT/nginx/ubuntu-host.conf" /etc/nginx/sites-available/agriculture-vision
    run_sudo ln -sfn /etc/nginx/sites-available/agriculture-vision /etc/nginx/sites-enabled/agriculture-vision
    run_sudo rm -f /etc/nginx/sites-enabled/default
    patched=1
  fi
  run_sudo nginx -t
  run_sudo systemctl restart nginx 2>/dev/null || run_sudo nginx -s reload
  echo "Ubuntu nginx reloaded: /api/ → 127.0.0.1:8000"
}

wait_http() {
  url="$1"
  i=0
  while [ "$i" -lt 25 ]; do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "OK $url"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "FAIL $url" >&2
  return 1
}

stop_old_forwards
if install_systemd_forward; then
  sleep 3
else
  echo "systemd unit not installed, using setsid port-forward"
  start_one_forward svc/api 8000:8000
  sleep 3
fi

wait_http "http://127.0.0.1:8000/api/v1/health"

ensure_api_hosts || true
patch_host_nginx || echo "WARNING: could not rewrite Ubuntu nginx (need passwordless sudo)" >&2

code=""
if curl -sf --max-time 5 "http://127.0.0.1/api/v1/health" >/dev/null 2>&1; then
  echo "OK http://127.0.0.1/api/v1/health"
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://127.0.0.1/api/v1/auth/login" -H 'Content-Type: application/json' -d '{}' || true)
elif curl -sf --max-time 5 "http://192.168.0.118/api/v1/health" >/dev/null 2>&1; then
  echo "OK http://192.168.0.118/api/v1/health"
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://192.168.0.118/api/v1/auth/login" -H 'Content-Type: application/json' -d '{}' || true)
else
  echo "FAIL host /api/v1/health still 502" >&2
  run_sudo grep -nE 'proxy_pass|server api|agrovision' /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* 2>/dev/null || true
  run_sudo tail -n 40 /var/log/nginx/error.log 2>/dev/null || true
  cat /tmp/av-pf-8000.log 2>/dev/null || true
  exit 1
fi

echo "POST /api/v1/auth/login → HTTP ${code} (expect 422, not 502)"
case "$code" in
  502|000|"")
    echo "login still not reaching FastAPI" >&2
    exit 1
    ;;
esac
exit 0
