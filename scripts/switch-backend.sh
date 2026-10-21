#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")/.."
touch .env

current() {  # value from .env (default if unset)
  local v; v=$(grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d "\"'" || true)
  echo "${v:-$2}"
}
set_var() {  # rewrite one KEY=value line in .env
  grep -vE "^$1=" .env > .env.tmp || true
  echo "$1=$2" >> .env.tmp
  mv .env.tmp .env
}

OLD_QUEUE=$(current QUEUE_BACKEND rabbitmq); OLD_CACHE=$(current CACHE_BACKEND redis)
NEW_QUEUE=$OLD_QUEUE; NEW_CACHE=$OLD_CACHE

for arg in "$@"; do
  case "$arg" in
    queue=rabbitmq|queue=postgres) NEW_QUEUE=${arg#queue=} ;;
    cache=redis|cache=postgres)    NEW_CACHE=${arg#cache=} ;;
    *) echo "unknown argument: $arg (use queue=rabbitmq|postgres and/or cache=redis|postgres)" >&2; exit 1 ;;
  esac
done

echo "queue backend: $OLD_QUEUE -> $NEW_QUEUE"
echo "cache backend: $OLD_CACHE -> $NEW_CACHE"
if [ "$NEW_QUEUE" = "$OLD_QUEUE" ] && [ "$NEW_CACHE" = "$OLD_CACHE" ]; then
  echo "nothing to change. Check what is running:  ssh history curl -s localhost:8002/api/status"
  exit 0
fi

set_var QUEUE_BACKEND "$NEW_QUEUE"
set_var CACHE_BACKEND "$NEW_CACHE"

if [ "$NEW_QUEUE" != "$OLD_QUEUE" ]; then
  vagrant provision fetcher --provision-with app-fetcher
  vagrant provision history --provision-with app-history
elif [ "$NEW_CACHE" != "$OLD_CACHE" ]; then
  vagrant provision history --provision-with app-history
fi

echo
echo "done. Active backends (from History itself):"
echo "  ssh history curl -s localhost:8002/api/status"
