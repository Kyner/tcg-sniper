# Segurança

## Como avisar de uma falha

Não abra issue pública para falha de segurança. Use o aviso privado do GitHub: aba **Security** do repositório → **Report a vulnerability**. Diga o que encontrou, como reproduzir e o que alguém consegue fazer com isso. A resposta vem pelo próprio aviso.

Interessa principalmente: o login pelo WhatsApp (código de acesso, sessões, limites), as permissões por papel da API, vazamento de segredos do `.env` ou de números de telefone, e qualquer caminho em que o coletor da Amazon faça algo além de conferir o preço (o coletor nunca confirma pedido nem mexe nos itens que a pessoa pôs no carrinho).

## Versões cobertas

Só o código atual da branch `main`.

## Como o projeto deve rodar hoje

O tcg-sniper roda numa rede de casa. O admin antigo (8000) e o noVNC (6080, 6081, 6082) usam HTTP sem TLS e não podem ficar expostos à internet; a Evolution API, o Postgres, a `api` e o `web` só escutam em `127.0.0.1`. Publicar na internet depende das pendências da seção "Segurança antes da internet" em [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md) e de um proxy com TLS e controle de acesso na frente (por exemplo Cloudflare Tunnel e Cloudflare Access).
