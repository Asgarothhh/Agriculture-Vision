#!/bin/sh
# docker-entrypoint.d: pick the container DNS so `proxy_pass http://$api_host`
# re-resolves after API/Service restarts (k8s and Compose).
set -eu
ns="$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf || true)"
[ -n "$ns" ] || ns="127.0.0.11"
printf 'resolver %s valid=10s ipv6=off;\n' "$ns" > /etc/nginx/resolver.conf
