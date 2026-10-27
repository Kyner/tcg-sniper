import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, Dados, Negrito, Severidade, TipoAviso
from tcg_sniper.avisos.formato import (
    LIMITE,
    UrlProibida,
    aviso_de,
    cabecalho,
    conferir_urls,
    eh_do_tipo,
    escapar,
    formatar,
    formatar_duracao,
    formatar_lembrete,
    formatar_resolvido,
)
from tcg_sniper.notificador.base import Destino

SP = ZoneInfo("America/Sao_Paulo")
QUANDO = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)  # 10:42 em São Paulo
HOST = "192.168.0.10"

ESPERADOS = {
    TipoAviso.LIGA_COLETA_CONCLUIDA: (
        "✅ *Liga · coleta concluída · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 3 produtos novos\n"
        "• Produtos: ok · 482 de 482 · casados 52, candidatos 18, novos 100, rodízio 312\n"
        "• Duração: 2 h 41 min\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_COLETA_PARCIAL: (
        "🟡 *Liga · coleta parcial · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 0 produtos novos\n"
        "• Produtos: parcial · 450 de 482 · casados 52, candidatos 18, novos 100, rodízio 312\n"
        "• Duração: 2 h 35 min\n"
        "\n"
        "*O que fazer:* Nada urgente; se repetir, veja Admin → Logs → LigaMagic.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_COLETA_FALHOU: (
        "🔴 *Liga · coleta falhou*\n"
        "• Etapa: Coleta dos produtos da lista do dia\n"
        "• Falhas: 300 de 412 produtos\n"
        "\n"
        "*O que fazer:* O layout da LigaMagic pode ter mudado: veja Admin → Logs → LigaMagic e os HTMLs na pasta falhas.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_DESAFIO: (
        "🔴 *Liga · desafio do Cloudflare*\n"
        "• Página: /?view=cards/search&card=categ%3D10\n"
        "• A coleta fica pausada até você retomar\n"
        "• 1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro por 24 h depois do desafio\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_PRODUTOS_NOVOS: (
        "🟡 *Liga · produtos novos no catálogo*\n"
        "• 3 produtos novos nas listagens\n"
        "\n"
        "*O que fazer:* Ative os que quiser acompanhar em Admin → Catálogo → filtro Novos.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_INTERROMPIDA: (
        "🟡 *Liga · coleta interrompida*\n"
        "• 2 coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job\n"
        "\n"
        "*O que fazer:* A coleta de hoje pode não rodar de novo sozinha: Admin → Serviços → LigaMagic → Rodar agora.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_ERRO: (
        "🔴 *Liga · erro inesperado*\n"
        "• Onde: Coleta dos produtos da lista do dia 41\n"
        "• Erro: TimeoutError('página não carregou')\n"
        "\n"
        "*O que fazer:* Veja os logs do coletor (docker compose logs coletor-liga); a próxima coleta tenta de novo.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.AMAZON_BUSCA_CONCLUIDA: (
        "✅ *Amazon · busca concluída · ciclo 42*\n"
        "• Buscas: 37 ok · 1 falha\n"
        "• Duração: 2 h 5 min\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_MONITOR_CONCLUIDO: (
        "✅ *Amazon · rodada do monitor*\n"
        "• Voltas da fila rápida: 4\n"
        "• Anúncios lidos: 96\n"
        "• Preços em queda: 2\n"
        "• Conferências de checkout: 1\n"
        "• Duração: 58 min\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_PARCIAL: (
        "🟡 *Amazon · busca parcial · ciclo 42*\n"
        "• Buscas: 30 ok · 8 falhas\n"
        "• Duração: 2 h 10 min\n"
        "\n"
        "*O que fazer:* Nada urgente; se repetir, veja Admin → Logs → Amazon.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_FALHOU: (
        "🔴 *Amazon · busca falhou · ciclo 42*\n"
        "• Buscas: 12 ok · 26 falhas\n"
        "• Duração: 1 h 40 min\n"
        "\n"
        "*O que fazer:* O layout da Amazon pode ter mudado: veja Admin → Logs → Amazon e os HTMLs na pasta falhas.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_CAPTCHA: (
        "🔴 *Amazon (busca) · CAPTCHA*\n"
        "• Página: /s?k=aetherdrift+commander\n"
        "• A busca fica pausada até você retomar; o monitor e a conferência seguem\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da busca (porta 6082) e depois Admin → Serviços → Amazon (busca) → Retomar.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_PAUSADA: (
        "🔴 *Amazon (busca) · pausada*\n"
        "• Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)\n"
        "• Com a busca pausada, o monitor e a conferência seguem\n"
        "\n"
        "*O que fazer:* Veja os logs (docker compose logs coletor-amazon-busca) e depois "
        "Admin → Serviços → Amazon (busca) → Retomar.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_ERRO: (
        "🟡 *Amazon (busca) · erro inesperado*\n"
        "• Erro: RuntimeError('navegador fechou')\n"
        "\n"
        "*O que fazer:* Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon-busca).\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_CAPTCHA: (
        "🔴 *Amazon (monitor) · CAPTCHA*\n"
        "• Página: /gp/cart/view.html\n"
        "• Monitor e conferência pausados até você retomar; a busca segue\n"
        "• Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
        "senão confira à mão\n"
        "\n"
        "*O que fazer:* Resolva no noVNC do monitor (porta 6081) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar.\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_SEM_LOGIN: (
        "🔴 *Amazon · conta sem login*\n"
        "• A conferência de checkout parou; o monitor de preço continua\n"
        "\n"
        "*O que fazer:* Faça login na conta Amazon pelo noVNC do monitor (porta 6081) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar conferência.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_CARRINHO: (
        "🔴 *Amazon · conferir o carrinho · B0DNV55QBS*\n"
        "• Pode haver 1× B0DNV55QBS de uma conferência automática no carrinho\n"
        "• Motivo: carrinho com outros itens (B0AAAA0001)\n"
        "\n"
        "*O que fazer:* Confira o carrinho pelo noVNC da Amazon (porta 6081), tire o item se não for seu e "
        "clique em Admin → Serviços → Já conferi.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_PAUSADA: (
        "🔴 *Amazon (monitor) · pausada*\n"
        "• Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)\n"
        "• Com o monitor pausado, a retirada automática de item do carrinho também para\n"
        "\n"
        "*O que fazer:* Veja os logs (docker compose logs coletor-amazon) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar.\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_ERRO: (
        "🟡 *Amazon (monitor) · erro inesperado*\n"
        "• Erro: RuntimeError('navegador fechou')\n"
        "\n"
        "*O que fazer:* Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_INTERROMPIDA: (
        "🟡 *Amazon (busca) · ciclo interrompido*\n"
        "• 1 ciclo(s) marcado(s) como falha: o serviço de busca reiniciou\n"
        "\n"
        "*O que fazer:* Nada a fazer: a fila continua sozinha.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.IA_RODADA_CONCLUIDA: (
        "✅ *IA · rodada concluída*\n"
        "• Avaliados: 12 anúncios em 5 produtos\n"
        "• Confirmados pelo automático: 3\n"
        "• Ignorados pelo automático: 5\n"
        "• Esperando você: 4\n"
        "\n"
        "*O que fazer:* Revise os pendentes em Admin → Casamentos.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_PAUSADA: (
        "🔴 *IA · casador pausado*\n"
        "• Motivo: chave recusada pela OpenAI (401)\n"
        "\n"
        "*O que fazer:* Corrija a chave da OpenAI (.env) ou Admin → Configurações → IA e depois "
        "Admin → Serviços → Casador → Retomar.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_SEM_ORCAMENTO: (
        "🟡 *IA · sem orçamento · dia 18/10*\n"
        "• Motivo: teto diário de US$ 1,00 atingido\n"
        "\n"
        "*O que fazer:* Volta sozinho no próximo período, ou suba o teto em Admin → Configurações → IA.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_FALHAS_SEGUIDAS: (
        "🟡 *IA · falhas seguidas*\n"
        "• 3 chamadas seguidas falharam; a rodada parou\n"
        "• Última: OpenAI 503\n"
        "\n"
        "*O que fazer:* Nada a fazer se for passageiro: a próxima rodada tenta de novo.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.BACKUP_CONCLUIDO: (
        "✅ *Backup · concluído · 18/10*\n"
        "• Tamanho: 607,3 KB\n"
        "• Cópia no R2: sim\n"
        "• Linhas antigas apagadas: 1.234\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.BACKUP_ERRO: (
        "🔴 *Backup · erro · 18/10*\n"
        "• Erro: envio ao R2 falhou: EndpointConnectionError\n"
        "• O backup local ficou salvo\n"
        "\n"
        "*O que fazer:* Tenta de novo amanhã às 04:00; veja Admin → Logs → Manutenção.\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.BACKUP_INTERROMPIDO: (
        "🟡 *Backup · interrompido*\n"
        "• 1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou\n"
        "\n"
        "*O que fazer:* Nada a fazer: o backup do dia roda de novo.\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.SERVICO_SEM_SINAL: (
        "🔴 *Serviço sem sinal · coletor-amazon*\n"
        "• Último sinal: 18/10 10:30 (há 12 min)\n"
        "\n"
        "*O que fazer:* Veja se o container está de pé (docker compose ps) e os logs dele.\n"
        "_18/10 10:42 · vigia_"
    ),
    TipoAviso.SERVICO_PAUSADO_MANUAL: (
        "🟡 *Serviço mudou no admin · Amazon*\n"
        "• Novo estado: pausado\n"
        "_18/10 10:42 · admin_"
    ),
    TipoAviso.MENSAGEM_NAO_ENVIADA: (
        "🔴 *WhatsApp · mensagem não enviada*\n"
        "• #123 para oportunidades: HTTP 400: grupo não encontrado\n"
        "\n"
        "*O que fazer:* Confira a instância e os grupos em Admin → Configurações → Geral e reenvie em "
        "Admin → Mensagens.\n"
        "_18/10 10:42 · notificador_"
    ),
    TipoAviso.OPORTUNIDADE: (
        "💰 *Oportunidade · 18% abaixo da Liga*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Amazon: *R$ 1.299,90* (conferido; frete à parte)\n"
        "• Vendido por: Amazon · Prime\n"
        "• Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.OPORTUNIDADE_ENCERRADA: (
        "⏹️ *Oferta encerrada · preço subiu*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Durou 3 h 20 min (desde 18/10 10:15)\n"
        "• Alerta: *R$ 1.299,90* → agora: *R$ 1.549,90*\n"
        "• Liga: a partir de R$ 1.589,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.OPORTUNIDADE_CORRIGIDA: (
        "⚠️ *Alerta corrigido*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• O alerta de 18/10 10:15 era de outro produto: desconsidere.\n"
        "_18/10 10:42 · casamentos_"
    ),
    TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO: (
        "🟡 *Oportunidade encerrada · anúncio sem leitura*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Durou 26 h 5 min (desde 18/10 10:15)\n"
        "\n"
        "*O que fazer:* Confira Admin → Serviços (LigaMagic e Amazon (monitor e checkout)).\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.CODIGO_ACESSO: (
        "🔑 *Código de acesso*\n"
        "*123456*\n"
        "• Vale por 5 minutos.\n"
        "• Não passe este código para ninguém.\n"
        "_18/10 10:42 · acesso_"
    ),
    TipoAviso.SEGURANCA_USUARIO: (
        "🟡 *Segurança · acesso alterado · papel alterado*\n"
        "• Usuário: Pessoa Exemplo\n"
        "• Papel: Grupo → Operador\n"
        "• Por: Pessoa Admin\n"
        "\n"
        "*O que fazer:* Se não foi alguém do grupo, desative o usuário em Gestão → Usuários.\n"
        "_18/10 10:42 · acesso_"
    ),
    TipoAviso.SEGURANCA_LIMITE: (
        "🟡 *Segurança · limite de códigos*\n"
        "• Limite: 3 códigos por número em 15 min\n"
        "• Número com final 34\n"
        "\n"
        "*O que fazer:* Se ninguém do grupo está tentando entrar, alguém pode estar testando números; "
        "o site recusa novos pedidos até a janela passar.\n"
        "_18/10 10:42 · acesso_"
    ),
}


def texto_de(tipo, dados=None, host=HOST, estrito=True):
    return formatar(aviso_de(tipo, dados or CATALOGO[tipo].exemplo, QUANDO), SP, host, estrito=estrito)


def test_catalogo_cobre_todos_os_tipos():
    assert set(CATALOGO) == set(TipoAviso) == set(ESPERADOS)
    assert len(TipoAviso) == 37


@pytest.mark.parametrize("tipo", list(TipoAviso))
def test_exemplo_de_cada_tipo_igual_ao_modelo(tipo):
    assert texto_de(tipo) == ESPERADOS[tipo]


def test_regras_do_catalogo():
    for tipo, d in CATALOGO.items():
        assert d.ligado_padrao is True, tipo
        assert (d.lembrete is not None) == d.agrupa, tipo
        destino = {
            TipoAviso.OPORTUNIDADE: Destino.OPORTUNIDADES,
            TipoAviso.OPORTUNIDADE_ENCERRADA: Destino.OPORTUNIDADES,
            TipoAviso.OPORTUNIDADE_CORRIGIDA: Destino.OPORTUNIDADES,
            TipoAviso.CODIGO_ACESSO: Destino.INDIVIDUAL,
        }
        assert d.grupo is destino.get(tipo, Destino.ADMIN), tipo
        if d.agrupa and tipo is not TipoAviso.MENSAGEM_NAO_ENVIADA:
            assert d.lembrete == timedelta(hours=2), tipo
        assert d.descricao, tipo
    assert CATALOGO[TipoAviso.MENSAGEM_NAO_ENVIADA].lembrete == timedelta(hours=1)
    assert CATALOGO[TipoAviso.OPORTUNIDADE].severidade is Severidade.OPORTUNIDADE
    assert CATALOGO[TipoAviso.CODIGO_ACESSO].severidade is Severidade.ACESSO
    agrupam = {t for t, d in CATALOGO.items() if d.agrupa}
    assert agrupam == {
        TipoAviso.LIGA_COLETA_FALHOU, TipoAviso.LIGA_DESAFIO, TipoAviso.LIGA_ERRO, TipoAviso.AMAZON_BUSCA_FALHOU,
        TipoAviso.AMAZON_CAPTCHA, TipoAviso.AMAZON_SEM_LOGIN, TipoAviso.AMAZON_CARRINHO, TipoAviso.AMAZON_PAUSADA,
        TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_BUSCA_CAPTCHA, TipoAviso.AMAZON_BUSCA_PAUSADA,
        TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.IA_PAUSADA, TipoAviso.IA_SEM_ORCAMENTO, TipoAviso.IA_FALHAS_SEGUIDAS,
        TipoAviso.BACKUP_ERRO, TipoAviso.SERVICO_SEM_SINAL, TipoAviso.MENSAGEM_NAO_ENVIADA,
        TipoAviso.SEGURANCA_LIMITE,
    }


def test_escapa_formatacao_vinda_dos_dados():
    dados = Dados(titulo_extra="*x*", destaque="_y_", linhas=("Erro: *a* _b_ ~c~ `d`", ("Preço: ", Negrito("R$ *1*"))))
    texto = texto_de(TipoAviso.AMAZON_ERRO, dados)
    assert texto.startswith("🟡 *Amazon (monitor) · erro inesperado · ∗x∗*\n*ˍyˍ*\n")
    assert "• Erro: ∗a∗ ˍbˍ ˜c˜ ˋdˋ\n" in texto
    assert "• Preço: *R$ ∗1∗*\n" in texto
    assert escapar("sem nada") == "sem nada"


def test_acao_dos_dados_substitui_a_padrao_e_none_some():
    sem = texto_de(TipoAviso.IA_RODADA_CONCLUIDA, Dados(linhas=("Avaliados: 1",)))
    assert "O que fazer" not in sem
    com = texto_de(TipoAviso.IA_RODADA_CONCLUIDA, Dados(linhas=("Avaliados: 1",), acao="Revise."))
    assert "\n\n*O que fazer:* Revise.\n_18/10 10:42 · casador (IA)_" in com


def test_corta_mensagem_longa_mantendo_titulo_acao_e_rodape():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=tuple("x" * 100 for _ in range(50))))
    assert len(texto) <= LIMITE
    assert texto.startswith("🟡 *Amazon (monitor) · erro inesperado*\n")
    assert "\n• …\n\n*O que fazer:* " in texto
    assert texto.endswith("_18/10 10:42 · monitor Amazon_")


def test_trecho_gigante_e_cortado():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=("y" * 5000,), titulo_extra="z" * 500))
    linhas = texto.split("\n")
    assert linhas[1] == "• " + "y" * 299 + "…"
    assert linhas[0] == "🟡 *Amazon (monitor) · erro inesperado · " + "z" * 119 + "…*"


@pytest.mark.parametrize(
    "linha",
    [
        "Veja http://192.168.0.10:8000/servicos",
        "noVNC em http://pc-de-casa:6081/vnc.html",
        "abra a porta :6080",
        "admin em algum-lugar:8000",
        "https://exemplo.com/caminho",
        "abra 192.168.0.10 no navegador",
    ],
)
def test_endereco_do_sistema_e_recusado_em_modo_estrito(linha):
    with pytest.raises(UrlProibida):
        texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=(linha,)))


def test_link_de_produto_de_outro_dominio_e_recusado():
    with pytest.raises(UrlProibida):
        texto_de(TipoAviso.OPORTUNIDADE, Dados(link_produto="https://evil.example/dp/B0X"))


def test_links_da_amazon_e_da_ligamagic_passam():
    dados = Dados(
        linhas=("Página: https://www.ligamagic.com.br/?view=cards/search",),
        link_produto="https://www.amazon.com.br/dp/B0TESTE123",
    )
    texto = texto_de(TipoAviso.OPORTUNIDADE, dados)
    assert "https://www.ligamagic.com.br/?view=cards/search" in texto
    assert "\nhttps://www.amazon.com.br/dp/B0TESTE123\n" in texto


def test_porta_sem_dois_pontos_e_preco_nao_sao_endereco():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=("noVNC da Amazon (porta 6081)", "R$ 6.080,00")))
    assert "porta 6081" in texto and "R$ 6.080,00" in texto


def test_fora_do_modo_estrito_remove_o_endereco_e_registra_no_log(caplog):
    caplog.set_level(logging.WARNING)
    dados = Dados(linhas=("Erro: ConnectError('http://192.168.0.10:8000/x')", "veja 192.168.0.10 e :6081"))
    texto = texto_de(TipoAviso.AMAZON_ERRO, dados, estrito=False)
    assert "• Erro: ConnectError('[endereço removido]')" in texto
    assert "• veja [endereço removido] e [endereço removido]" in texto
    assert "192.168" not in texto and "8000" not in texto
    assert "endereço do sistema removido" in caplog.text


def test_conferir_urls_sem_host_so_olha_portas_e_dominios():
    assert conferir_urls("tudo certo", None, estrito=True) == "tudo certo"


def test_lembrete_no_mesmo_dia_e_em_outro_dia():
    aviso = aviso_de(TipoAviso.AMAZON_CAPTCHA, CATALOGO[TipoAviso.AMAZON_CAPTCHA].exemplo, QUANDO)
    mesmo = formatar_lembrete(aviso, 3, QUANDO - timedelta(hours=2), SP, HOST, estrito=True)
    assert mesmo.startswith("🔴 *Amazon (monitor) · CAPTCHA continua · 3 vezes desde 08:42*\n• Página: /gp/cart/view.html")
    assert mesmo.endswith("_18/10 10:42 · monitor Amazon_")
    outro = formatar_lembrete(aviso, 9, QUANDO - timedelta(days=1), SP, HOST, estrito=True)
    assert outro.startswith("🔴 *Amazon (monitor) · CAPTCHA continua · 9 vezes desde 17/10 10:42*\n")


def test_resolvido_com_e_sem_chave():
    geral = formatar_resolvido(TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL, 2, QUANDO - timedelta(minutes=30), QUANDO, SP)
    assert geral == "✅ *Amazon (monitor) · CAPTCHA resolvido · 2 vezes em 30 min*\n_18/10 10:42 · monitor Amazon_"
    carrinho = formatar_resolvido(TipoAviso.AMAZON_CARRINHO, "B0DNV55QBS", 1, QUANDO - timedelta(hours=2), QUANDO, SP)
    assert carrinho == "✅ *Amazon · conferir o carrinho · B0DNV55QBS resolvido · 1 vez em 2 h*\n_18/10 10:42 · coletor Amazon_"


@pytest.mark.parametrize(
    ("duracao", "texto"),
    [
        (timedelta(seconds=30), "menos de 1 min"),
        (timedelta(seconds=-5), "menos de 1 min"),
        (timedelta(minutes=30), "30 min"),
        (timedelta(hours=2), "2 h"),
        (timedelta(hours=1, minutes=12), "1 h 12 min"),
        (timedelta(hours=26), "1 d 2 h"),
        (timedelta(days=2), "2 d"),
    ],
)
def test_duracao(duracao, texto):
    assert formatar_duracao(duracao) == texto


def test_hora_no_fuso_pedido():
    texto = formatar(aviso_de(TipoAviso.SERVICO_PAUSADO_MANUAL, Dados(), QUANDO), ZoneInfo("UTC"), estrito=True)
    assert texto.endswith("_18/10 13:42 · admin_")


def test_cabecalho_reconhece_o_tipo_tambem_no_lembrete():
    assert cabecalho(TipoAviso.MENSAGEM_NAO_ENVIADA) == "🔴 *WhatsApp · mensagem não enviada"
    aviso = aviso_de(TipoAviso.MENSAGEM_NAO_ENVIADA, CATALOGO[TipoAviso.MENSAGEM_NAO_ENVIADA].exemplo, QUANDO)
    assert eh_do_tipo(formatar(aviso, SP, estrito=True), TipoAviso.MENSAGEM_NAO_ENVIADA)
    assert eh_do_tipo(formatar_lembrete(aviso, 2, QUANDO, SP, estrito=True), TipoAviso.MENSAGEM_NAO_ENVIADA)
    assert not eh_do_tipo("🔴 *Amazon · CAPTCHA*", TipoAviso.MENSAGEM_NAO_ENVIADA)


def test_cada_origem_da_amazon_tem_titulo_proprio():
    titulos = {CATALOGO[t].titulo for t in (
        TipoAviso.AMAZON_CAPTCHA, TipoAviso.AMAZON_BUSCA_CAPTCHA, TipoAviso.AMAZON_PAUSADA,
        TipoAviso.AMAZON_BUSCA_PAUSADA, TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_BUSCA_ERRO,
    )}
    assert len(titulos) == 6
    assert all(t.startswith(("Amazon (busca) · ", "Amazon (monitor) · ")) for t in titulos)


def test_porta_6082_tambem_e_endereco_do_sistema():
    with pytest.raises(UrlProibida):
        texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=("veja http://10.0.0.2:6082/vnc.html",)))
