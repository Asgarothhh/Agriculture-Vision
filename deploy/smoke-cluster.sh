#!/bin/sh
# Smoke the cluster from the runner host. Kept out of .gitlab-ci.yml so GitLab
# does not expand $IP ($$ becomes the shell PID and curl exits 6).
set -eu

IP="$(minikube ip)"
echo "minikube ip: ${IP}"

echo "GET :30800/api/v1/health"
curl -fsS "http://${IP}:30800/api/v1/health"
echo

echo "GET :30080/api/v1/health"
curl -fsS "http://${IP}:30080/api/v1/health"
echo

code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://${IP}:30800/api/v1/auth/login" \
  -H 'Content-Type: application/json' -d '{}' || true)"
echo "login ${code}"
test "$code" != "502" -a "$code" != "000"
