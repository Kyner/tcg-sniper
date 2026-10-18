# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir e anotar o commit. Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-17.

## 1. Acompanhar (sem código)

- [x] Primeiro dia do monitor de preço e da conferência de checkout (deploy `32c80a4`), 2026-10-18 às 08:36: 49 de 51 anúncios lidos (129 leituras); 1 conferência ok (Kit Inicial Final Fantasy, anunciado R$ 161,47 → conferido R$ 155,52 = 129,28 + 26,24 de imposto, item removido); 1 alerta com preço conferido; nada preso no carrinho, sem "sem login".
- [ ] Frequência de CAPTCHA da Amazon com o monitor ligado (até 150 páginas/h).
- [ ] Uma semana de coletas da LigaMagic sem desafio do Cloudflare.

## 2. Pequenas, desta última entrega (fazer juntas)

- [x] "oferta 0 do painel sem preço legível": não perdia oferta. Em 5 dos 51 anúncios a Amazon não tem oferta em destaque ("Nenhuma opção de compra em destaque") e o bloco fixo só traz foto e título; as ofertas da lista eram lidas normalmente. O leitor agora pula esse bloco sem aviso (branch `fix/painel-sem-destaque`).
- [x] "Monitor rodou antes da janela": não é bug. As janelas da busca e do monitor variam até 15 min para não parecer robô (texto de ajuda em Configurações já diz isso).

- [x] Teste `tests/admin/test_admin_dashboard.py::test_dashboard_mostra_ultimas_execucoes_e_horario` depende do horário: falha depois das 22:00 (card da Amazon mostra "fora do horário"). Fixar o relógio no teste. Relógio fixo em 12:00 (monkeypatch de `repo.agora_utc`); o resto dos testes do admin rodou às 23:30 e às 06:00 sem outra dependência do horário (branch `fix/pacote-a`).
- [x] Monitor: depois de uma conferência que falhou com "a oferta não está mais no painel", não mandar o alerta com o preço anunciado já velho (`monitor.redecidir`); deixar a próxima leitura decidir. `redecidir` não faz nada com esse motivo (`checkout.MOTIVO_OFERTA_SUMIU`); as outras falhas continuam avisando com o anunciado.
- [x] Monitor: não mandar REALERTAR com preço anunciado (sem imposto) quando a oportunidade já foi alertada com preço conferido e nenhuma conferência pode rodar. Nova coluna `oportunidade.alerta_conferido` (migração `c8f2d6a1e4b9`); com ela, a queda pelo anunciado só atualiza a aberta, sem aviso, até um novo conferido.
- [x] Incluir `/logs` (abas) no `scripts/verificar_layout.py`. `/logs` e as abas amazon, ia, checkout e monitor nas telas fixas.

## 3. Pequenas, antigas

- [x] Ofertas: arredondamento do filtro de desconto (24,996% passa no "≥ 25%"). O filtro compara o desconto exato (`atinge_desconto`); a tela mostra o desconto arredondado para baixo (24,99%).
- [x] Dashboard/Logs: aba da Amazon reabrindo depois de paginar a LigaMagic com filtro ativo — conferir se ainda acontece na tela de Logs. Não acontece em `/logs`: o teste novo passou de primeira e fica como guarda.
- [x] htmx carregado sem SRI (integridade do script). `integrity` sha384 (igual ao publicado pelo htmx 1.9.12) e `crossorigin="anonymous"`.
- [x] Checkout: um clique bloqueado pela trava ainda conta como página no teto por hora; mensagem de carrinho ocupado com contagem certa quando o contador lê 0. Clique recusado antes de clicar (trava ou botão ausente) não conta; com contador 0 a mensagem usa os itens ativos.
- [ ] Anonimizador: número de rua sozinho em `proibidos.txt` troca dígitos dentro de preços/ASIN; preço sem centavos depois de "final" vira "cartão"; CPF/CNPJ e telefone fixo sem parênteses não são pegos. (Só importa numa nova captura.)
- [ ] Trava de cliques: varredura AST não pega `eval_on_selector`/`evaluate_all`/`submit()`/`getattr`; caracteres Unicode parecidos (ex.: "о" cirílico). Defesa extra, sem falha conhecida.

- [ ] Retirada do carrinho: quando o clique de excluir falha, a página aberta não entra no teto por hora (`cliques.remover_do_carrinho`).
- [ ] `abrir_oportunidade`/`atualizar_oportunidade`: tornar `conferido` obrigatório (hoje padrão False) para um chamador futuro não registrar alerta conferido como anunciado.

## 4. Proteção e operação (recomendado antes de crescer)

- [ ] **Backup automático do banco**: `pg_dump` diário, com rodízio (ex.: 7 diários + 4 semanais) e cópia fora do PC. Hoje só há backups manuais antes de cada deploy (`dados/backups/`).
- [ ] **Limpeza de histórico**: já existe limpeza de 30 dias para `oferta_amazon` e `mensagem_saida`. Ainda crescem sem limite: `preco_amazon`, `resumo_preco`/preços da Liga, `chamada_ia`, `conferencia_checkout`, `coleta`. Definir retenção por tabela.
- [ ] Bancos de teste (`tcg_test*`) ficam no mesmo Postgres de produção: separar num container próprio.
- [ ] Riscos conhecidos (decisão, não código): o PC é ponto único de falha; o número do WhatsApp pode ser banido (usar chip secundário).

## 5. Próximas funcionalidades (decisão do grupo)

- [ ] **Margem líquida real** por oportunidade: comissão de lojista da LigaMagic, frete de envio, imposto, cupons e cartões. Precisa dos valores/regras do grupo.
- [ ] **Coletor do Mercado Livre** pelo navegador (sem API).
- [ ] **Limite de exposição por produto** (quanto o grupo aceita comprar de cada item).
- [ ] **Outros sites** de compra.
- [ ] **Migrar para servidor** (a LigaMagic continua sendo coletada em casa).
- [ ] Imagens no R2 da Cloudflare: só se for preciso mostrar fotos no admin ou guardar histórico de imagem (hoje a IA baixa direto da loja).

## Ordem sugerida

1. Seção 1 (acompanhar) nos próximos dias.
2. Seção 2 inteira + "filtro de desconto" da seção 3, num pacote só.
3. Backup automático (seção 4).
4. Retenção do histórico (seção 4).
5. Margem líquida (seção 5), quando o grupo tiver os valores.

## Concluídas recentemente

- [x] Monitor de preço da Amazon com conferência de checkout, descoberta só para quem não tem par, origem do casamento (`32c80a4`, 2026-10-17).
- [x] Dashboard de visão geral, Serviços liga/desliga, tela de Logs (`9e0e07f`).
- [x] Automático da IA aplica avaliações antigas (`44aec0f`).
- [x] Casamento com IA (OpenAI), nome em inglês da LigaMagic, admin em DaisyUI.
