#!/bin/sh
set -e
: "${VNC_SENHA:?defina VNC_SENHA no .env}"

export DISPLAY=:99
rm -f /tmp/.X99-lock

Xvfb :99 -screen 0 1366x768x24 &
sleep 1
fluxbox >/dev/null 2>&1 &
x11vnc -display :99 -forever -shared -passwd "$VNC_SENHA" -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

exec tcg-sniper coletor-liga
