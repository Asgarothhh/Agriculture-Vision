#!/bin/sh
# Point the Ubuntu host nginx (:80, the remote-access address) at the cluster nginx.
# The cluster nginx (NodePort 30080) serves the SPA built for this commit plus
# /api/ and /basemap/esri/, so the host never serves a stale frontend again.
# Needs passwordless sudo; without it the step is skipped with a warning.
set -eu

NAMESPACE="${KUBE_NAMESPACE:-ml-service}"
WEB_NODEPORT="${AV_WEB_NODEPORT:-30080}"
EXPECTED_SHA="${CI_COMMIT_SHORT_SHA:-}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
SITE_NAME="agriculture-vision"

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi
  sudo -n "$@"
}

can_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  command -v sudo >/dev/null 2>&1 || return 1
  sudo -n true >/dev/null 2>&1
}

fetch() {
  curl -fsS --noproxy '*' --max-time 5 "$1" 2>/dev/null
}

wait_version() {
  url="$1"
  i=0
  while [ "$i" -lt 30 ]; do
    if body="$(fetch "$url")"; then
      echo "$body"
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  return 1
}

IP="$(minikube ip 2>/dev/null || true)"
if [ -z "$IP" ]; then
  echo "refresh-host-nginx: minikube ip is unknown" >&2
  exit 1
fi
UPSTREAM="http://${IP}:${WEB_NODEPORT}"
if ! cluster_version="$(wait_version "${UPSTREAM}/version.json")"; then
  echo "refresh-host-nginx: cluster nginx is not reachable at ${UPSTREAM}" >&2
  kubectl get svc,pods -n "$NAMESPACE" -o wide || true
  exit 1
fi
echo "cluster nginx ${UPSTREAM}: ${cluster_version}"

if ! command -v nginx >/dev/null 2>&1; then
  echo "refresh-host-nginx: no host nginx installed, nothing to do"
  exit 0
fi
if ! can_sudo; then
  echo "WARNING: no passwordless sudo — host nginx on :80 was NOT repointed to ${UPSTREAM}." >&2
  echo "WARNING: the remote-access address may still serve an old frontend. Run as root: sh deploy/refresh-host-nginx.sh" >&2
  exit 0
fi

tmp="$(mktemp)"
# A stock Ubuntu nginx.conf includes sites-enabled/ and conf.d/: install a site.
# A hand-copied full nginx.conf (deploy/nginx/ubuntu-nginx.conf) has its own :80
# server and no includes: replace nginx.conf itself.
if run_sudo grep -qE '^[[:space:]]*include[[:space:]]+/etc/nginx/(sites-enabled|conf\.d)/' /etc/nginx/nginx.conf; then
  sed "s|__WEB_UPSTREAM__|${UPSTREAM}|g" "$ROOT/nginx/ubuntu-host.conf" > "$tmp"
  if [ -d /etc/nginx/sites-available ]; then
    target="/etc/nginx/sites-available/${SITE_NAME}"
  else
    target="/etc/nginx/conf.d/${SITE_NAME}.conf"
  fi
else
  sed "s|__WEB_UPSTREAM__|${UPSTREAM}|g" "$ROOT/nginx/ubuntu-nginx.conf" > "$tmp"
  target="/etc/nginx/nginx.conf"
fi
echo "host nginx: installing ${target} → ${UPSTREAM}"

backups=""
created=""
backup() {
  f="$1"
  if [ -e "$f" ] || [ -L "$f" ]; then
    run_sudo cp -P "$f" "${f}.bak-av"
    backups="${backups} ${f}"
  else
    created="${created} ${f}"
  fi
}
restore() {
  for f in $created; do
    run_sudo rm -f "$f"
  done
  for f in $backups; do
    run_sudo mv -f "${f}.bak-av" "$f"
  done
}

backup "$target"
run_sudo cp "$tmp" "$target"
rm -f "$tmp"
if [ "$target" = "/etc/nginx/sites-available/${SITE_NAME}" ]; then
  backup /etc/nginx/sites-enabled/default
  backup "/etc/nginx/sites-enabled/${SITE_NAME}"
  run_sudo ln -sfn "$target" "/etc/nginx/sites-enabled/${SITE_NAME}"
  # Another server on :80 (default site, older copies) would shadow this one.
  run_sudo rm -f /etc/nginx/sites-enabled/default
fi

if ! run_sudo nginx -t; then
  echo "refresh-host-nginx: nginx -t failed, restoring the previous config" >&2
  restore
  exit 1
fi
if ! run_sudo nginx -T 2>/dev/null | grep -q "proxy_pass ${UPSTREAM};"; then
  echo "refresh-host-nginx: ${target} is not loaded — /etc/nginx/nginx.conf does not include" >&2
  echo "refresh-host-nginx: sites-enabled/*.conf or conf.d/*.conf. Add the include (or replace nginx.conf)" >&2
  restore
  exit 1
fi
run_sudo systemctl reload nginx 2>/dev/null || run_sudo nginx -s reload
for f in $backups; do
  run_sudo rm -f "${f}.bak-av"
done

if ! host_version="$(wait_version "http://127.0.0.1/version.json")"; then
  echo "refresh-host-nginx: host :80 does not answer /version.json" >&2
  exit 1
fi
echo "host :80 → ${UPSTREAM}: ${host_version}"
if [ -n "$EXPECTED_SHA" ] && ! printf '%s' "$host_version" | grep -q "$EXPECTED_SHA"; then
  echo "refresh-host-nginx: host :80 serves ${host_version}, expected ${EXPECTED_SHA}" >&2
  exit 1
fi
code="$(curl -sS --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 5 -X POST "http://127.0.0.1/api/v1/auth/login" \
  -H 'Content-Type: application/json' -d '{}' || true)"
echo "host POST /api/v1/auth/login → HTTP ${code} (expect 422)"
case "$code" in
  502|000|"") exit 1 ;;
esac
