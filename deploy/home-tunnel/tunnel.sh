#!/usr/bin/env bash
# Обратный туннель: домашний интернет становится выходом для CrossParts.
#
# Запускается НА ВАШЕЙ машине (домашний ПК, ноутбук, мини-ПК), не на сервере.
# Поднимает локальный SOCKS5 и пробрасывает его на сервер, где сервис берёт
# его как CP_PROXY_URL=socks5://127.0.0.1:1081
#
#   SERVER=mrb-cross-search-test.duckdns.org ./tunnel.sh
set -euo pipefail

SERVER="${SERVER:?укажите SERVER=хост.сервера}"
SSH_USER="${SSH_USER:-tunnel}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/crossparts_tunnel}"
LOCAL_SOCKS_PORT="${LOCAL_SOCKS_PORT:-1080}"
REMOTE_PORT="${REMOTE_PORT:-1081}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "нужен $1: $2"; exit 1; }; }
need ssh "apt install openssh-client / встроен в Windows 10+ и macOS"

start_socks() {
  if command -v microsocks >/dev/null 2>&1; then
    microsocks -i 127.0.0.1 -p "$LOCAL_SOCKS_PORT" &
    echo $!
  elif command -v ssh >/dev/null 2>&1; then
    # Запасной вариант: SOCKS через ssh на самого себя не нужен —
    # ставим microsocks: apt install microsocks / brew install microsocks
    echo "Установите microsocks: sudo apt install microsocks (или brew install microsocks)" >&2
    exit 1
  fi
}

if ! ss -ltn 2>/dev/null | grep -q ":$LOCAL_SOCKS_PORT " && \
   ! netstat -an 2>/dev/null | grep -q "\.$LOCAL_SOCKS_PORT .*LISTEN"; then
  echo "Поднимаю локальный SOCKS5 на 127.0.0.1:$LOCAL_SOCKS_PORT"
  SOCKS_PID=$(start_socks)
  trap 'kill "$SOCKS_PID" 2>/dev/null || true' EXIT
  sleep 1
fi

echo "Туннель $SERVER:$REMOTE_PORT -> ваш SOCKS5:$LOCAL_SOCKS_PORT"
echo "На сервере укажите: CP_PROXY_URL=socks5://127.0.0.1:$REMOTE_PORT"

# -R слушает на 127.0.0.1 сервера: прокси не будет открыт наружу.
# Keepalive + автопереподключение: домашний интернет иногда отваливается.
while true; do
  ssh -N \
      -i "$SSH_KEY" \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new \
      -R "127.0.0.1:$REMOTE_PORT:127.0.0.1:$LOCAL_SOCKS_PORT" \
      "$SSH_USER@$SERVER" || true
  echo "$(date '+%H:%M:%S') связь потеряна, переподключаюсь через 10 с…"
  sleep 10
done
