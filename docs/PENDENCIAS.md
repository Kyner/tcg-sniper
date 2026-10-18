# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-18.

## 1. Acompanhar (sem código)

- [ ] Frequência de CAPTCHA da Amazon com o monitor ligado (até 150 páginas/h).
- [ ] Uma semana de coletas da LigaMagic sem desafio do Cloudflare.

## 2. Pacote B: proteção e operação (próximo a fazer)

- [ ] Bancos de teste (`tcg_test*`) ficam no mesmo Postgres de produção: separar num container próprio.

## 3. Pequenas (sem pressa, juntar num pacote)

- [ ] Retirada do carrinho: quando o clique de excluir falha, a página aberta não entra no teto por hora (`cliques.remover_do_carrinho`).
- [ ] `abrir_oportunidade`/`atualizar_oportunidade`: tornar `conferido` obrigatório (hoje padrão False) para um chamador futuro não registrar alerta conferido como anunciado.
- [ ] Trava de cliques: varredura AST não pega `eval_on_selector`/`evaluate_all`/`submit()`/`getattr`; caracteres Unicode parecidos (ex.: "о" cirílico). Defesa extra, sem falha conhecida.
- [ ] Anonimizador: número de rua sozinho em `proibidos.txt` troca dígitos dentro de preços/ASIN; preço sem centavos depois de "final" vira "cartão"; CPF/CNPJ e telefone fixo sem parênteses não são pegos. (Só importa numa nova captura.)

## 4. Próximas funcionalidades (decisão do grupo)

- [ ] **Margem líquida real** por oportunidade: comissão de lojista da LigaMagic, frete de envio, imposto, cupons e cartões. Precisa dos valores/regras do grupo.
- [ ] **Coletor do Mercado Livre** pelo navegador (sem API).
- [ ] **Limite de exposição por produto** (quanto o grupo aceita comprar de cada item).
- [ ] **Outros sites** de compra.
- [ ] **Migrar para servidor** (a LigaMagic continua sendo coletada em casa).
- [ ] Imagens no R2 da Cloudflare: só se for preciso mostrar fotos no admin ou guardar histórico de imagem (hoje a IA baixa direto da loja).

## 5. Riscos conhecidos (decisão, não código)

- [ ] O PC é ponto único de falha (ver "Migrar para servidor").
- [ ] O número do WhatsApp pode ser banido: usar chip secundário.

## Ordem sugerida

1. Seção 1 (acompanhar) nos próximos dias.
2. Pacote B (seção 2): limpeza do histórico (prazos aprovados) e backup automático (cópia no R2 precisa das credenciais).
3. Seção 3 quando houver outra mexida no coletor da Amazon.
4. Margem líquida (seção 4), quando o grupo tiver os valores.

## Concluídas

### Pacote B (2026-10-18)

- [x] **Backup automático do banco**: serviço `manutencao` (compose), todo dia às 04:00 no fuso de Configurações → Geral, com recuperação ao subir se o último ok tem mais de 24 h. `pg_dump -Fc` validado com `pg_restore --list`, rodízio de 7 diários + 4 semanais em `dados/backups/` (os `tcg-antes-*.dump` manuais nunca são tocados) e cópia no R2 (`diario/`, `semanal/`; o bucket expira sozinho). Card Backup no Dashboard, liga/desliga em Serviços, Logs → Manutenção; falha avisa o grupo admin uma vez (`ef4c008`, `e79560f`, `1011a75`, `7ab2ed4`). Falta a primeira cópia real no R2 com as credenciais.
- [x] **Limpeza de histórico** (`db/retencao.py`, na mesma execução diária, só depois de um backup local ok) (`c006baa`):
  - preços (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`), `avaliacao_ia` e `oportunidade`: nunca apagados;
  - `chamada_ia`: 90 dias; antes de apagar, `avaliacao_ia.chamada_id` vira NULL (a avaliação fica; nenhuma tela junta a chamada pela avaliação);
  - `conferencia_checkout`: 180 dias, só com `item_removido` (as que ainda podem ter item no carrinho ficam);
  - `coleta`: 180 dias, só as que nenhum preço referencia (`resumo_preco`, `preco_listagem`, `preco_atual_liga`): rodadas que falharam ou vieram vazias e os ciclos da Amazon. Nunca uma `rodando`;
  - `oferta_amazon` e `mensagem_saida` continuam com a limpeza de 30 dias de antes (coletor-amazon e notificador).

### Pacote A (2026-10-18)

- [x] Teste do Dashboard dependia do horário (falhava depois das 22:00): relógio fixo em 12:00 (`b9308b1`).
- [x] Monitor: conferência que falhou com "a oferta não está mais no painel" não manda alerta com o preço anunciado velho; a próxima leitura decide (`599a6f2`).
- [x] Monitor: sem REALERTAR com preço anunciado (sem imposto) depois de alerta com preço conferido; nova coluna `oportunidade.alerta_conferido`, migração `c8f2d6a1e4b9` (`7402c3c`).
- [x] `/logs` e abas no `scripts/verificar_layout.py` (`65a134b`).
- [x] Logs: aba da Amazon reabrindo ao paginar a LigaMagic com filtro não acontece mais; teste fica de guarda (`1f61efd`).
- [x] Ofertas: filtro de desconto compara o valor exato; tela mostra arredondado para baixo (24,99%) (`dd1ca0a`).
- [x] htmx com SRI (`integrity` sha384 + `crossorigin`) (`07ec5a0`).
- [x] Checkout: clique recusado pela trava não conta no teto por hora; mensagem de carrinho ocupado com contagem certa (`0990367`).

### Antes

- [x] Painel da Amazon sem oferta em destaque: leitor pula o bloco sem aviso, não perdia oferta (`619b892`).
- [x] "Monitor rodou antes da janela": não é bug, janelas variam até 15 min de propósito.
- [x] Primeiro dia do monitor e da conferência de checkout (2026-10-18): 49 de 51 anúncios lidos, 1 conferência ok (imposto somado, item removido), 1 alerta com preço conferido, nada preso no carrinho.
- [x] Monitor de preço da Amazon com conferência de checkout, descoberta só para quem não tem par, origem do casamento (`32c80a4`, 2026-10-17).
- [x] Dashboard de visão geral, Serviços liga/desliga, tela de Logs (`9e0e07f`).
- [x] Automático da IA aplica avaliações antigas (`44aec0f`).
- [x] Casamento com IA (OpenAI), nome em inglês da LigaMagic, admin em DaisyUI.
