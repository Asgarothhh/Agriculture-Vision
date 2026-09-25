#!/bin/sh
# Spec §9–10: Nginx на :80 отдаёт фронт и проксирует /api/ → FastAPI
#   curl http://localhost/api/v1/health
# На 192.168.0.118 Ubuntu nginx/1.24 уже отдаёт статику (/ → 200),
# а /api/ даёт 502: апстрим 127.0.0.1:8000 пустой после перехода на minikube.
set -eu

NAMESPACE="${KUBE_NAMESPACE:-ml-service}"
KUBECTL="$(command -v kubectl || true)"

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
  echo "systemd agriculture-vision-forward enabled (127.0.0.1:8000 → svc/api)"
}

wait_http() {
  url="$1"
  i=0
  while [ "$i" -lt 20 ]; do
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
# optional: in-cluster nginx on 30080 for direct checks
start_one_forward svc/agri-nginx-service 30080:80 || true

wait_http "http://127.0.0.1:8000/api/v1/health"
wait_http "http://127.0.0.1:8000/api/v1/ready" || true

if curl -sf --max-time 5 "http://127.0.0.1/api/v1/health" >/dev/null 2>&1 \
   || curl -sf --max-time 5 "http://192.168.0.118/api/v1/health" >/dev/null 2>&1; then
  echo "OK host /api/v1/health  (spec §10.2)"
else
  echo "WARNING: API is on :8000 but Ubuntu nginx /api/ still 502 — check proxy_pass" >&2
  run_sudo grep -R "proxy_pass" /etc/nginx/ 2>/dev/null || true
  run_sudo tail -n 30 /var/log/nginx/error.log 2>/dev/null || true
  cat /tmp/av-pf-8000.log 2>/dev/null || true
  run_sudo systemctl status agriculture-vision-forward.service --no-pager 2>/dev/null || true
fi
exit 0
