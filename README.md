# tcg-sniper

Monitor de arbitragem de selados de Magic. Sub-projeto 1: coleta diária da LigaMagic, página de admin e alertas no grupo admin do WhatsApp.

Design: `docs/superpowers/specs/2026-10-13-coletor-liga-design.md`.

## Como funciona

- Um job por dia, por volta das 10:00 (± 30 min, fuso `America/Sao_Paulo`; `COLETA_HORA`, `COLETA_JITTER_MIN`).
- Primeiro, as listagens de todas as categorias de selados (`LIGA_CATEGORIAS`), clicando em "Exibir mais" pelo botão, com pausa humana antes de cada clique e no máximo `LIGA_MAX_CLIQUES` cliques. Daí saem o catálogo (`produto_liga`) e o preço "à partir de" atual de cada produto.
- Depois, a página de cada produto marcado como ativo no admin. Daí saem o número de lojas e o resumo do histórico de venda (mín, médio, máx).
- Só o resumo: as ofertas por vendedor são ofuscadas na página e nunca são decodificadas nem expandidas.
- Pausa aleatória de 8 a 20 s entre páginas. Nunca há duas coletas ao mesmo tempo.
- Se aparecer um desafio do Cloudflare, a coleta pausa, avisa o grupo admin e espera uma pessoa. Não há solucionador de CAPTCHA nem nova tentativa automática.

## Desenvolvimento

```
docker compose up -d postgres
uv sync
uv run playwright install chromium
cp .env.example .env   # ajuste os valores
uv run pytest
TESTAR_NAVEGADOR=1 uv run pytest tests/coletor_liga/test_navegador.py   # opcional: abre um Chromium com uma página local
```

## Subir tudo

> **Atenção:** o primeiro `up` do `coletor-liga` acessa a LigaMagic de verdade. Se ainda não houver nenhum job com sucesso, ele começa uma coleta completa em até ~30 min, mesmo que já tenha passado das 10:00. Suba o `coletor-liga` quando alguém puder acompanhar pelo noVNC.

1. Copie `.env.example` para `.env` e defina:
   - `ADMIN_SENHA` (o admin não sobe com valor vazio ou o padrão);
   - `VNC_SENHA` (o coletor não sobe com valor vazio ou o padrão; o VNC só usa os **8 primeiros caracteres**);
   - `EVOLUTION_API_KEY` (com valor vazio ou o padrão, os alertas vão só para o log);
   - `HOST_PUBLICO` (IP do PC na rede local).

   `LIGA_CATEGORIAS`, `LIGA_URL_LISTAGEM` e `LIGA_MAX_CLIQUES` já vêm com os valores levantados em 2026-10-13. Uma categoria que passe a falhar todo dia (ex.: ficou vazia) sai de `LIGA_CATEGORIAS`.
2. Suba tudo, menos o coletor: `docker compose up -d --build postgres evolution migrate admin`.
   - O `docker/postgres-init.sql` (que cria os bancos `evolution` e `tcg_test`) só roda num volume novo. Se o volume `pgdata` já existia, crie o banco à mão: `docker compose exec postgres psql -U tcg -c "CREATE DATABASE evolution;"`.
3. Conecte o WhatsApp. Use um **chip secundário, nunca um número pessoal ou da loja**:
   - `curl -X POST http://localhost:8080/instance/create -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" -d '{"instanceName":"tcg-sniper","integration":"WHATSAPP-BAILEYS","qrcode":true}'`
   - Leia o QR code devolvido (ou `GET /instance/connect/tcg-sniper`) com o WhatsApp do chip.
   - Adicione o número ao grupo admin e descubra o ID: `curl "http://localhost:8080/group/fetchAllGroups/tcg-sniper?getParticipants=false" -H "apikey: $EVOLUTION_API_KEY"`.
   - Grave o ID (`...@g.us`) em `WHATSAPP_GRUPO_ADMIN`.
4. Com alguém acompanhando, suba o coletor: `docker compose up -d coletor-liga`.
5. Admin: `http://<HOST_PUBLICO>:8000` (usuário qualquer, senha `ADMIN_SENHA`).
6. noVNC (para resolver um desafio do Cloudflare): `http://<HOST_PUBLICO>:6080/vnc.html` (senha `VNC_SENHA`).

O admin e o noVNC usam HTTP simples, sem TLS: são só para a rede local. Não exponha as portas 8000 e 6080 para a internet. A Evolution API (8080) e o Postgres (5432) só escutam em `127.0.0.1`.

## Quando chegar um aviso de desafio

O Chromium fica aberto com a verificação na tela. Abra o noVNC, resolva a verificação nessa janela e clique em **Retomar** no admin. Em até 1 minuto o job do dia roda de novo no mesmo navegador (com as listagens, se nenhuma terminou com sucesso hoje). O coletor não tenta de novo sozinho. Se a janela do Chromium for fechada, o próximo job abre outra.
