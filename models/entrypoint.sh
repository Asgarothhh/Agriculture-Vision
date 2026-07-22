#!/bin/sh
set -e
mkdir -p /models
# Копируем только отсутствующие файлы (не перезаписываем обновлённые веса)
for f in /seed/*; do
  [ -e "$f" ] || continue
  name=$(basename "$f")
  if [ ! -f "/models/$name" ]; then
    echo "[models] seeding $name → /models/"
    cp -a "$f" "/models/$name"
  else
    echo "[models] keep existing /models/$name"
  fi
done
ls -lah /models || true
echo "[models] ready, sleeping"
exec sleep infinity
