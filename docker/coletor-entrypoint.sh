#!/bin/sh
# Sobe a área de trabalho virtual (Xvfb + fluxbox), o VNC (só localhost) e o noVNC na porta 6080,
# e então executa o comando do container (padrão: tcg-sniper coletor-liga).
set -e

SENHA_PADRAO="trocar-esta-senha"
senha_limpa=$(printf '%s' "${VNC_SENHA:-}" | tr -d '[:space:]')
if [ -z "$senha_limpa" ] || [ "$VNC_SENHA" = "$SENHA_PADRAO" ]; then
    echo "erro: defina VNC_SENHA no .env (vazia ou '$SENHA_PADRAO' não são aceitas; o VNC usa só os 8 primeiros caracteres)" >&2
    exit 1
fi

# Arquivo de senha só legível pelo processo; a senha nunca aparece na linha de comando.
umask 077
ARQ_SENHA=/tmp/vnc-senha
printf '%s\n' "$VNC_SENHA" > "$ARQ_SENHA"
umask 022

# Restos de uma execução anterior (container reiniciado ou parado à força).
# Só um coletor usa o volume, então os locks do perfil do Chromium são sempre obsoletos aqui.
# DIR_PERFIL separa o perfil de cada coletor (Liga: <DIR_DADOS>/perfil; Amazon: <DIR_DADOS>/perfil-amazon).
PERFIL="${DIR_PERFIL:-${DIR_DADOS:-/data}/perfil}"
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 \
    "$PERFIL/SingletonLock" "$PERFIL/SingletonSocket" "$PERFIL/SingletonCookie"

export DISPLAY=:99
Xvfb :99 -screen 0 1366x768x24 &

espera=0
until [ -S /tmp/.X11-unix/X99 ]; do
    espera=$((espera + 1))
    if [ "$espera" -gt 100 ]; then
        echo "erro: Xvfb não abriu o display :99 em 10 s" >&2
        exit 1
    fi
    sleep 0.1
done

fluxbox >/dev/null 2>&1 &
x11vnc -display :99 -localhost -forever -shared -passwdfile "$ARQ_SENHA" -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 127.0.0.1:5900 >/dev/null 2>&1 &

if [ "$#" -eq 0 ]; then
    set -- tcg-sniper coletor-liga
fi
exec "$@"
