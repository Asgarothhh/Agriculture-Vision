#!/bin/sh
# Ubuntu nginx :80 → static SPA; /api/ → FastAPI (spec §9–10).
# Host nginx still has `server api:8000` (k8s DNS). Replace that upstream with
# something reachable from the host: minikube NodePort, else a systemd port-forward.
set -eu

NAMESPACE="${KUBE_NAMESPACE:-ml-service}"
NODEPORT="${AV_API_NODEPORT:-30800}"
KUBECTL="$(command -v kubectl || true)"
ROOT="$(cd "$(dirname "$0")" && pwd)"

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi
  command -v sudo >/dev/null 2>&1 || return 1
  sudo -n "$@"
}

reachable() {
  curl -sf --max-time 3 "$1" >/dev/null 2>&1
}

wait_http() {
  url="$1"
  i=0
  while [ "$i" -lt 30 ]; do
    if reachable "$url"; then
      echo "OK $url"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "FAIL $url" >&2
  return 1
}

start_systemd_forward() {
  [ -n "$KUBECTL" ] || return 1
  command -v systemctl >/dev/null 2>&1 || return 1
  run_sudo true || return 1
  kubeconfig="${KUBECONFIG:-$HOME/.kube/config}"
  unit=/etc/systemd/system/agriculture-vision-forward.service
  run_sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=Agriculture-Vision API port-forward
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
  wait_http "http://127.0.0.1:8000/api/v1/health"
}

pick_upstream() {
  if command -v minikube >/dev/null 2>&1; then
    IP="$(minikube ip 2>/dev/null || true)"
    if [ -n "$IP" ] && wait_http "http://${IP}:${NODEPORT}/api/v1/health"; then
      UPSTREAM="http://${IP}:${NODEPORT}"
      return 0
    fi
  fi
  if reachable "http://127.0.0.1:8000/api/v1/health"; then
    UPSTREAM="http://127.0.0.1:8000"
    return 0
  fi
  if start_systemd_forward; then
    UPSTREAM="http://127.0.0.1:8000"
    return 0
  fi
  echo "API is not reachable from the host on NodePort ${NODEPORT} or :8000" >&2
  kubectl get svc,pods -n "$NAMESPACE" -o wide || true
  return 1
}

patch_nginx_upstream() {
  hostport="${UPSTREAM#http://}"
  run_sudo true || return 1
  patched=0
  for f in /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* /etc/nginx/sites-available/* /etc/nginx/conf.d/*.conf; do
    [ -f "$f" ] || continue
    if run_sudo grep -qE 'api:8000|agrovision_api|127\.0\.0\.1:8000|30800|30080' "$f"; then
      echo "patch $f → ${UPSTREAM}"
      run_sudo cp "$f" "${f}.bak-av"
      run_sudo sed -i \
        -e "s|server[[:space:]]\+api:8000|server ${hostport}|g" \
        -e "s|http://api:8000|${UPSTREAM}|g" \
        -e "s|http://\$api_upstream|${UPSTREAM}|g" \
        -e "s|http://127\.0\.0\.1:8000|${UPSTREAM}|g" \
        -e "s|http://[0-9.]\+:30800|${UPSTREAM}|g" \
        -e "s|http://[0-9.]\+:30080|${UPSTREAM}|g" \
        "$f"
      patched=1
    fi
  done
  if [ "$patched" -eq 0 ]; then
    tmp="$(mktemp)"
    sed "s|__API_UPSTREAM__|${UPSTREAM}|g" "$ROOT/nginx/ubuntu-host.conf" > "$tmp"
    if [ -d /etc/nginx/sites-available ]; then
      run_sudo cp "$tmp" /etc/nginx/sites-available/agriculture-vision
      run_sudo ln -sfn /etc/nginx/sites-available/agriculture-vision /etc/nginx/sites-enabled/agriculture-vision
      run_sudo rm -f /etc/nginx/sites-enabled/default
    elif [ -d /etc/nginx/conf.d ]; then
      run_sudo cp "$tmp" /etc/nginx/conf.d/agriculture-vision.conf
    else
      rm -f "$tmp"
      echo "could not find a place to install nginx /api/ location" >&2
      return 1
    fi
    rm -f "$tmp"
  fi
  if ! run_sudo nginx -t; then
    echo "nginx -t failed, restoring backups" >&2
    for f in /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
      [ -f "${f}.bak-av" ] || continue
      run_sudo mv "${f}.bak-av" "$f"
    done
    return 1
  fi
  run_sudo systemctl reload nginx 2>/dev/null || run_sudo nginx -s reload
  echo "Ubuntu nginx /api/ → ${UPSTREAM}"
}

pick_upstream
patch_nginx_upstream

if reachable "http://127.0.0.1/api/v1/health" || reachable "http://192.168.0.118/api/v1/health"; then
  echo "OK host /api/v1/health"
else
  echo "FAIL host /api/ still 502" >&2
  run_sudo grep -nE 'proxy_pass|server ' /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* 2>/dev/null || true
  run_sudo tail -n 30 /var/log/nginx/error.log 2>/dev/null || true
  exit 1
fi

code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://127.0.0.1/api/v1/auth/login" \
  -H 'Content-Type: application/json' -d '{}' || true)
echo "POST /api/v1/auth/login → HTTP ${code} (expect 422, not 502)"
case "$code" in
  502|000|"")
    echo "login still not reaching FastAPI" >&2
    exit 1
    ;;
esac
exit 0
