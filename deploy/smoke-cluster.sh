#!/bin/sh
# Smoke the cluster from the runner. Kept out of .gitlab-ci.yml so GitLab
# does not expand $IP ($$ becomes the shell PID and curl exits 6).
# NodePort on the minikube docker bridge can refuse for a moment after rollout
# (kube-proxy has not programmed endpoints yet) or stay closed on the host
# while the Service is healthy inside the cluster. Retry the host, then ask
# the pods directly.
# Finally check that the Celery worker has loaded the SegFormer weights and
# the API sees them (models are loaded only in the worker, see
# app/ml_service/health_store.py) — otherwise segmentation is dead in the UI.
set -eu

NS="${KUBE_NAMESPACE:-ml-service}"
ML_WAIT_ATTEMPTS="${ML_WAIT_ATTEMPTS:-36}"
IP="$(minikube ip)"
echo "minikube ip: ${IP}"

host_get() {
  curl -fsS --noproxy '*' --connect-timeout 2 --max-time 10 "$1"
}

in_cluster_smoke() {
  echo "NodePort ${IP}:30800/30080 is not reachable from the runner; checking Services inside the cluster" >&2

  echo "GET api /api/v1/health"
  kubectl exec -n "$NS" deploy/agriculture-vision-api -c fastapi-api -- \
    python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=10).read().decode())"

  echo "GET nginx /api/v1/health"
  kubectl exec -n "$NS" deploy/agriculture-vision-nginx -- \
    wget -qO- http://127.0.0.1/api/v1/health
  echo

  code="$(kubectl exec -n "$NS" deploy/agriculture-vision-api -c fastapi-api -- \
    python -c "
import urllib.error, urllib.request
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/auth/login',
    data=b'{}',
    headers={'Content-Type': 'application/json'},
    method='POST',
)
try:
    urllib.request.urlopen(req, timeout=10)
    print(200)
except urllib.error.HTTPError as exc:
    print(exc.code)
")"
  echo "login ${code}"
  test "$code" != "502" -a "$code" != "000"
}

ml_smoke() {
  echo "ML: waiting for the worker to load SegFormer"
  n=0
  while [ "$n" -lt "$ML_WAIT_ATTEMPTS" ]; do
    if kubectl exec -n "$NS" deploy/agriculture-vision-api -c fastapi-api -- \
      python -c "
import json, sys
from app.ml_service.health_store import get_ml_health
health = get_ml_health()
print(json.dumps(health, ensure_ascii=False))
seg = [m for m in health.get('models', []) if m.get('code') == 'segformer']
sys.exit(0 if seg and seg[0].get('loaded') else 1)
"; then
      echo "ML: segformer loaded"
      return 0
    fi
    n=$((n + 1))
    echo "ML: segformer not loaded yet (attempt ${n}/${ML_WAIT_ATTEMPTS}), retrying" >&2
    sleep 5
  done
  echo "ML: segformer is not loaded in the worker — segmentation will not work" >&2
  return 1
}

host_ok=0
i=0
while [ "$i" -lt 15 ]; do
  if host_get "http://${IP}:30800/api/v1/health" \
    && host_get "http://${IP}:30080/api/v1/health"; then
    echo
    host_ok=1
    break
  fi
  i=$((i + 1))
  echo "NodePort not ready (attempt ${i}/15), retrying" >&2
  sleep 2
done

if [ "$host_ok" -eq 1 ]; then
  code="$(curl -sS --noproxy '*' -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 10 \
    -X POST "http://${IP}:30800/api/v1/auth/login" \
    -H 'Content-Type: application/json' -d '{}' || true)"
  echo "login ${code}"
  test "$code" != "502" -a "$code" != "000"
else
  in_cluster_smoke
fi

ml_smoke
