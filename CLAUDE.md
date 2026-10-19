# Regras de trabalho do tcg-sniper

Valem para toda sessão neste repositório. O repositório é público: nada de dados pessoais aqui.

## Idioma e commits

- Textos, docs, telas e mensagens em português. Assunto dos commits em inglês, no estilo `tipo: descrição` (`feat:`, `fix:`, `docs:`, `test:`, `merge:`).
- **Sem assinatura de IA** em commits e PRs: nada de `Co-Authored-By` de IA, `Claude-Session` ou "Generated with".
- Commit, push, merge e deploy só quando o usuário pedir.

## Deploy e dados

- Backup do banco antes de todo deploy com migração.
- Deploy de todos os serviços juntos: `docker compose up -d --build`.
- Nunca mostrar segredos do `.env` (nem em log, nem em saída de comando).
- Nada gravado fora do repositório (ou das worktrees dele) sem perguntar.
- Parar qualquer servidor que a sessão subiu antes de terminar.
- Histórico de preço nunca é apagado (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`, `avaliacao_ia`, `oportunidade`).

## Testes

- Testes rodam no Postgres de teste (container `postgres-teste`, `127.0.0.1:5433`, bancos `tcg_test*`). Os testes recusam a porta 5432 e bancos fora de `tcg_test*`.

## Interface

- Admin antigo e site novo (`web/`): só componentes do DaisyUI 5, com classes escritas por extenso (literais, nada montado por concatenação). Não inventar visual próprio.
- O front (React) fica a cargo do assistente.

## Amazon

- Preço conferido = itens + impostos, **sem frete** (frete mostrado à parte).
- Nunca confirmar pedido, nunca clicar em "Comprar agora", nunca mexer nos itens que o usuário pôs no carrinho. O coletor só remove o que ele mesmo adicionou para conferir.

## Negócio

- O grupo vende como lojista na LigaMagic. Sem API da LigaMagic nem do Mercado Livre (coleta pelo navegador). Avisos só pelo WhatsApp.
- O acesso às oportunidades vai ser vendido depois: assinantes no mesmo sistema, **sem multi-cliente**. Limites e sessões pensados para crescer.

## Papéis e permissões (resumo)

- Papéis fixos: `grupo`, `operador`, `admin`. O que cada papel pode fazer é configurável na grade papel × permissão (Gestão → Acessos); o admin tem sempre todas.
- Um único **superadmin**, criado e trocado só pelo terminal (`tcg-sniper criar-superadmin`, `trocar-superadmin`). Nunca é rebaixado, desativado nem tem sessões encerradas pelo site.
- Só o superadmin cria, edita, rebaixa ou desativa admins e encerra sessões de admins; admins comuns gerenciam só operadores e grupo.
- Toda rota da API declara a permissão que exige.

## Pendências

- `docs/PENDENCIAS.md` é a lista única do que falta. Ler antes de começar e atualizar no mesmo commit de cada entrega (marcar `[x]`, anotar o commit, mover para "Concluídas").
- Specs e planos ficam em `docs/superpowers/specs/` e `docs/superpowers/plans/`.
