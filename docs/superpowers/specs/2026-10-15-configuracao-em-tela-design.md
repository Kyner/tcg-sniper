# Configuração em tela: Geral, LigaMagic e Amazon

Data: 2026-10-15
Contexto: a Amazon (`2026-10-14-coletor-amazon-design.md`) já guarda a configuração no banco (`config_amazon`) e a edita em **Configurações**. O resto ainda vem do `.env`.

## Objetivo

Ajustar pelo admin tudo o que é operação, sem editar arquivo nem reiniciar container. A tela **Configurações** passa a ter três seções: **Geral**, **LigaMagic** e **Amazon**.

Critério de sucesso: o grupo muda, pelo admin, o horário da coleta da Liga, as categorias, o grupo de WhatsApp ou o IP dos links, e a mudança vale no próximo ciclo (ou na próxima mensagem) sem ninguém mexer no `.env` nem no Docker.

## Escopo

Dentro:

- Tabelas `config_geral` e `config_liga` (uma linha cada), no padrão da `config_amazon`.
- Leitura da configuração do banco a cada ciclo nos coletores, a cada página no admin e a cada envio no notificador.
- Tela Configurações com três seções independentes.
- Valores iniciais copiados do `.env` atual; `.env.example` e README atualizados.

Fora:

- Mudar os campos da Amazon (só mudam de rota).
- Histórico de alterações ou quem alterou.
- Levar para a tela o que é infraestrutura ou segredo (abaixo).

## Decisões de 2026-10-15

1. A mudança vale no próximo ciclo, sem reiniciar (opção 1).
2. Ficam no `.env`: `DATABASE_URL`, `DIR_DADOS`, `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `VNC_SENHA` e `ADMIN_SENHA`. São lidos antes do banco existir, por outro container (a Evolution lê `EVOLUTION_API_KEY`; o script de entrada lê `VNC_SENHA`) ou protegem a própria tela.
3. Abordagem: duas tabelas de uma linha com colunas tipadas e `CHECK`, iguais à `config_amazon` (não uma tabela chave/valor, nem tudo numa tabela só).

## O que vai para a tela

| Seção | Campo (coluna) | Variável de hoje | Regra |
|---|---|---|---|
| Geral | `host_publico` | `HOST_PUBLICO` | texto não vazio, sem espaços |
| Geral | `fuso` | `FUSO` | fuso IANA válido (`ZoneInfo`), conferido no Python |
| Geral | `evolution_instancia` | `EVOLUTION_INSTANCIA` | texto; vazio = sem WhatsApp |
| Geral | `whatsapp_grupo_admin` | `WHATSAPP_GRUPO_ADMIN` | vazio ou terminado em `@g.us` |
| Geral | `whatsapp_grupo_oportunidades` | `WHATSAPP_GRUPO_OPORTUNIDADES` | vazio ou terminado em `@g.us` |
| LigaMagic | `coleta_hora` | `COLETA_HORA` | hora (HH:MM) |
| LigaMagic | `coleta_jitter_min` | `COLETA_JITTER_MIN` | 0 a 180 |
| LigaMagic | `pausa_min_s`, `pausa_max_s` | `PAUSA_MIN_S`, `PAUSA_MAX_S` | 0 a 120; mínima ≤ máxima |
| LigaMagic | `limite_falha_pct` | `LIMITE_FALHA_PCT` | 0 a 100 |
| LigaMagic | `categorias` | `LIGA_CATEGORIAS` | IDs numéricos separados por vírgula, ao menos um; duplicados removidos |
| LigaMagic | `url_listagem` | `LIGA_URL_LISTAGEM` | contém `{categ}` |
| LigaMagic | `max_cliques` | `LIGA_MAX_CLIQUES` | 1 a 500 |

Os limites numéricos e as regras de texto que o SQL expressa (`{categ}` na URL, mínima ≤ máxima, linha única `id = 1`) também viram `CHECK` no banco. A pausa ganha teto de 120 s (no `.env` não tinha), igual à Amazon.

## Dados

- `config_geral` e `config_liga`: `id` fixo 1 (`CHECK id = 1`), uma coluna por campo acima.
- Repositório (`db/repositorio.py`): `obter_config_geral(s, padrao)`, `obter_config_liga(s, padrao)`, `salvar_config_geral(s, valores)`, `salvar_config_liga(s, valores)`. `padrao` é o `Config` do `.env`.
- **Valores iniciais:** a migração só cria as tabelas. Na primeira leitura, se a linha não existe, `obter_*` a cria com os valores do `Config` do `.env` atual (que, sem `.env`, são os padrões de hoje). Assim o deploy não muda nenhum comportamento.

## Leitura (quando a mudança vale)

`carregar_config(sessoes, config_env) -> Config` lê as duas linhas e devolve uma cópia do `Config` com os valores do banco por cima (`model_copy(update=...)`). O código que usa `config.host_publico`, `config.coleta_hora`, `config.categorias` etc. não muda. As variáveis migradas que ainda estiverem no `.env` são ignoradas: vale o banco.

- **Coletor da Liga (agendador):** recarrega a cada `tick` (a cada minuto) e no começo de cada job; o job em andamento termina com os valores com que começou. Se `coleta_hora`, `coleta_jitter_min` ou `fuso` mudarem e o job de hoje ainda não rodou, o alvo do dia é sorteado de novo; se já rodou, nada muda até o dia seguinte. A execução atrasada (`_atrasada_em`) já sorteada é mantida.
- **Coletor da Amazon:** já relê `config_amazon` a cada ciclo; passa a recarregar também a geral (links das mensagens e fuso da janela).
- **Admin:** recarrega a cada requisição (fuso do filtro de datas, horário da coleta no Dashboard, "fora da janela", links).
- **Notificador do WhatsApp:** o `EvolutionNotificador` passa a ler instância e grupos do banco a cada envio (função injetada que devolve a configuração geral). Grupo vazio, instância vazia ou chave padrão/vazia continuam mandando só para o log, como hoje. A URL e a chave da Evolution continuam vindo do `.env`.

## Tela Configurações (`/configuracoes`)

- Três seções, nesta ordem: **Geral**, **LigaMagic**, **Amazon**, cada uma com o seu formulário e o seu botão **Salvar**.
- Rotas: `POST /configuracoes/geral`, `POST /configuracoes/liga`, `POST /configuracoes/amazon` (a rota atual `POST /configuracoes` da Amazon passa a ser esta; campos da Amazon iguais).
- Erro de validação: status 400, a seção volta com os valores digitados e a mensagem ao lado do campo; as outras seções mostram o que está salvo. Sucesso: redireciona para `/configuracoes?msg=<geral|liga|amazon>` com "Salvo; vale a partir da próxima coleta ou ciclo".
- Cada campo tem uma frase de ajuda (adaptada do `.env.example`).
- **Categorias:** campo de texto; abaixo, as categorias padrão (`CATEGORIAS_SELADOS`) e o link "restaurar padrão", que preenche o campo (sem salvar).
- Rodapé: "Senhas, banco e chave da Evolution ficam no `.env`: `ADMIN_SENHA`, `VNC_SENHA`, `EVOLUTION_API_KEY`, `DATABASE_URL`, `DIR_DADOS`, `EVOLUTION_URL`."

## Deploy e documentação

- Migração nova cria `config_geral` e `config_liga`. Backup do banco antes, como nos deploys anteriores.
- Deploy: `migrate`, `admin`, `coletor-liga` e `coletor-amazon`. O primeiro serviço que ler cria as linhas com os valores do `.env`; nenhum comportamento muda.
- `.env.example`: saem as variáveis migradas, com uma nota apontando para Configurações no admin.
- README: a seção de configuração passa a descrever a tela; as instruções que mandam editar `.env` para essas variáveis (ex.: grupos do WhatsApp no passo 5) passam a mandar para a tela. O usuário pode apagar essas linhas do seu `.env` quando quiser.

## Testes

- Validação de cada campo e limite (tela e `CHECK`): pausa mínima > máxima, categorias vazias/não numéricas, URL sem `{categ}`, fuso inválido, grupo sem `@g.us`, valores fora da faixa → 400 sem gravar.
- Primeira leitura cria a linha com os valores do `Config` passado.
- `carregar_config` sobrepõe os valores do banco aos do `.env`.
- Agendador: mudar `coleta_hora` antes do job de hoje sorteia novo alvo no próximo `tick`; depois do job, não muda; job em andamento usa os valores do início.
- Notificador: grupo trocado no banco vale na mensagem seguinte; grupo vazio vai para o log.
- Admin: datas no fuso salvo; Dashboard mostra o horário salvo.
- Seções salvam de forma independente; erro em uma não altera as outras.
- O teste que compara os modelos com as migrações continua passando.
