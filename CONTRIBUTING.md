# Como contribuir

Issues e pull requests são bem-vindos. Antes de um PR grande, abra uma issue para combinar o caminho: a lista do que falta e das decisões já tomadas fica em [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md).

## Regras do projeto

- **Idioma.** Código, telas, mensagens e documentação em português. O assunto do commit em inglês, no formato `tipo: descrição` (`feat:`, `fix:`, `docs:`, `test:`).
- **Sem dados pessoais.** O repositório é público: nada de números de telefone, IDs de grupo, CEPs, contas ou páginas capturadas sem anonimizar (`scripts/anonimizar_fixture.py` para a Amazon, `scripts/recortar_fixture.py` para a LigaMagic).
- **Ritmo de coleta.** Não aceitamos mudança que aumente o ritmo padrão de acesso aos sites, que resolva CAPTCHA sozinha ou que disfarce o navegador. Ver [Uso responsável](README.md#uso-responsável).
- **Amazon.** O coletor nunca confirma pedido, nunca usa "Comprar agora" e só remove do carrinho o que ele mesmo adicionou para conferir. O preço conferido é itens + impostos, sem frete.
- **Histórico de preço** nunca é apagado (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`, `avaliacao_ia`, `oportunidade`).
- **Interface.** Admin antigo e site novo (`web/`) usam só componentes do DaisyUI 5, com as classes escritas por extenso (nada montado por concatenação), sem CSS próprio.
- **API.** Toda rota declara a permissão que exige.

## Antes de abrir o PR

```bash
docker compose up -d postgres-teste
uv run pytest -q
uv run ruff check
(cd web && npm test && npm run build)   # se mexeu no front
```

Os testes rodam só no `postgres-teste` (`127.0.0.1:5433`, bancos `tcg_test*`) e nunca acessam a LigaMagic, a Amazon ou o WhatsApp reais. Detalhes em [Desenvolvimento](README.md#desenvolvimento).

Ao contribuir, você concorda que sua contribuição fica sob a [licença MIT](LICENSE) do projeto.
