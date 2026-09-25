#!/bin/sh
# Ubuntu nginx :80 serves the SPA; /api/ → FastAPI NodePort on minikube (spec §9–10).
# No kubectl port-forward: it dies when the GitLab job ends and login goes 502 again.
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
NODEPORT="${AV_API_NODEPORT:-30800}"

if ! command -v minikube >/dev/null 2>&1; then
  echo "minikube not found" >&2
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

IP="$(minikube ip)"
UPSTREAM="http://${IP}:${NODEPORT}"
echo "API upstream for Ubuntu nginx: ${UPSTREAM}"

wait_http() {
  url="$1"
  i=0
  while [ "$i" -lt 25 ]; do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo "OK $url"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "FAIL $url" >&2
  return 1
}

wait_http "${UPSTREAM}/api/v1/health"

render() {
  sed "s|__API_UPSTREAM__|${UPSTREAM}|g" "$1"
}

install_host_nginx() {
  run_sudo true || return 1
  tmp="$(mktemp)"
  if [ -f /etc/nginx/nginx.conf ] && run_sudo grep -qE 'api:8000|agrovision_api|pid /tmp/nginx.pid|__API_UPSTREAM__|30800|30080' /etc/nginx/nginx.conf; then
    render "$ROOT/nginx/ubuntu-nginx.conf" > "$tmp"
    run_sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak-av
    run_sudo cp "$tmp" /etc/nginx/nginx.conf
  elif [ -d /etc/nginx/sites-available ]; then
    render "$ROOT/nginx/ubuntu-host.conf" > "$tmp"
    run_sudo cp "$tmp" /etc/nginx/sites-available/agriculture-vision
    run_sudo ln -sfn /etc/nginx/sites-available/agriculture-vision /etc/nginx/sites-enabled/agriculture-vision
    run_sudo rm -f /etc/nginx/sites-enabled/default
  elif [ -d /etc/nginx/conf.d ]; then
    render "$ROOT/nginx/ubuntu-host.conf" > "$tmp"
    run_sudo cp "$tmp" /etc/nginx/conf.d/agriculture-vision.conf
  else
    echo "no nginx site dir found" >&2
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"

  # leftover k8s hostname in any remaining site
  for f in /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [ -f "$f" ] || continue
    if run_sudo grep -qE 'server[[:space:]]+api:8000|http://api:8000' "$f"; then
      run_sudo sed -i.bak-av \
        -e "s|server[[:space:]]\+api:8000|server ${IP}:${NODEPORT}|g" \
        -e "s|http://api:8000|${UPSTREAM}|g" \
        "$f"
    fi
  done

  run_sudo nginx -t
  run_sudo systemctl restart nginx 2>/dev/null || run_sudo nginx -s reload
  echo "Ubuntu nginx /api/ → ${UPSTREAM}"
}

install_host_nginx

if curl -sf --max-time 5 "http://127.0.0.1/api/v1/health" >/dev/null 2>&1 \
   || curl -sf --max-time 5 "http://192.168.0.118/api/v1/health" >/dev/null 2>&1; then
  echo "OK host /api/v1/health"
else
  echo "FAIL host /api/ still 502 after nginx reload" >&2
  run_sudo grep -nE 'proxy_pass|server ' /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* 2>/dev/null || true
  run_sudo tail -n 40 /var/log/nginx/error.log 2>/dev/null || true
  exit 1
fi

code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://127.0.0.1/api/v1/auth/login" \
  -H 'Content-Type: application/json' -d '{}' || true)
if [ "$code" = "000" ] || [ -z "$code" ]; then
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://192.168.0.118/api/v1/auth/login" \
    -H 'Content-Type: application/json' -d '{}' || true)
fi
echo "POST /api/v1/auth/login → HTTP ${code} (expect 422, not 502)"
case "$code" in
  502|000|"")
    echo "login still not reaching FastAPI" >&2
    exit 1
    ;;
esac
exit 0
