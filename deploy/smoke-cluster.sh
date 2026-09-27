#!/bin/sh
# Smoke the cluster from the runner. Kept out of .gitlab-ci.yml so GitLab
# does not expand $IP ($$ becomes the shell PID and curl exits 6).
# NodePort on the minikube docker bridge can refuse for a moment after rollout
# (kube-proxy has not programmed endpoints yet) or stay closed on the host
# while the Service is healthy inside the cluster. Retry the host, then ask
# the pods directly.
set -eu

NS="${KUBE_NAMESPACE:-ml-service}"
IP="$(minikube ip)"
echo "minikube ip: ${IP}"

host_get() {
  curl -fsS --noproxy '*' --connect-timeout 2 --max-time 10 "$1"
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
  exit 0
fi

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
