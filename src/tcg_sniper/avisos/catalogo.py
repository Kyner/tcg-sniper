"""Catálogo dos avisos do WhatsApp: um tipo por evento, com severidade, grupo, título, regra de repetição,
ação padrão e um exemplo com dados fictícios (tela Avisos e testes)."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from tcg_sniper.notificador.base import Destino

CHAVE_GERAL = "geral"  # ocorrências sem distinção: um problema só por tipo
DUAS_HORAS = timedelta(hours=2)


class Severidade(StrEnum):
    FALHA = "falha"
    ATENCAO = "atencao"
    CONCLUIDO = "concluido"
    OPORTUNIDADE = "oportunidade"
    ACESSO = "acesso"


EMOJI = {
    Severidade.FALHA: "🔴",
    Severidade.ATENCAO: "🟡",
    Severidade.CONCLUIDO: "✅",
    Severidade.OPORTUNIDADE: "💰",
    Severidade.ACESSO: "🔑",
}
EMOJI_RESOLVIDO = "✅"


class TipoAviso(StrEnum):
    LIGA_COLETA_CONCLUIDA = "liga_coleta_concluida"
    LIGA_COLETA_PARCIAL = "liga_coleta_parcial"
    LIGA_COLETA_FALHOU = "liga_coleta_falhou"
    LIGA_DESAFIO = "liga_desafio"
    LIGA_PRODUTOS_NOVOS = "liga_produtos_novos"
    LIGA_INTERROMPIDA = "liga_interrompida"
    LIGA_ERRO = "liga_erro"
    AMAZON_BUSCA_CONCLUIDA = "amazon_busca_concluida"
    AMAZON_MONITOR_CONCLUIDO = "amazon_monitor_concluido"
    AMAZON_BUSCA_PARCIAL = "amazon_busca_parcial"
    AMAZON_BUSCA_FALHOU = "amazon_busca_falhou"
    AMAZON_CAPTCHA = "amazon_captcha"
    AMAZON_SEM_LOGIN = "amazon_sem_login"
    AMAZON_CARRINHO = "amazon_carrinho"
    AMAZON_PAUSADA = "amazon_pausada"
    AMAZON_ERRO = "amazon_erro"
    AMAZON_INTERROMPIDA = "amazon_interrompida"
    IA_RODADA_CONCLUIDA = "ia_rodada_concluida"
    IA_PAUSADA = "ia_pausada"
    IA_SEM_ORCAMENTO = "ia_sem_orcamento"
    IA_FALHAS_SEGUIDAS = "ia_falhas_seguidas"
    BACKUP_CONCLUIDO = "backup_concluido"
    BACKUP_ERRO = "backup_erro"
    BACKUP_INTERROMPIDO = "backup_interrompido"
    SERVICO_SEM_SINAL = "servico_sem_sinal"
    SERVICO_PAUSADO_MANUAL = "servico_pausado_manual"
    MENSAGEM_NAO_ENVIADA = "mensagem_nao_enviada"
    OPORTUNIDADE = "oportunidade"
    CODIGO_ACESSO = "codigo_acesso"
    SEGURANCA_USUARIO = "seguranca_usuario"
    SEGURANCA_LIMITE = "seguranca_limite"


@dataclass(frozen=True)
class Negrito:
    """Trecho de dado que sai em negrito (é escapado e depois envolvido em `*`)."""

    texto: str


Trecho = str | Negrito
Linha = str | tuple[Trecho, ...]


@dataclass(frozen=True)
class Dados:
    """O que varia em cada ocorrência. Tudo aqui é dado (escapado no formato), menos `acao`, que é texto
    nosso e substitui a ação padrão do tipo (None: fica a padrão)."""

    linhas: tuple[Linha, ...] = ()
    titulo_extra: str | None = None
    destaque: str | None = None  # linha em negrito logo abaixo do título (ex.: nome do produto)
    acao: str | None = None
    link_produto: str | None = None  # só Amazon ou LigaMagic


@dataclass(frozen=True)
class DefinicaoAviso:
    severidade: Severidade
    grupo: Destino
    titulo: str
    origem: str  # rodapé: quem mandou
    descricao: str  # quando sai (tela Avisos)
    exemplo: Dados
    agrupa: bool = False
    lembrete: timedelta | None = None
    acao: str | None = None
    ligado_padrao: bool = True


LIGA, AMAZON, MONITOR, IA = "coletor Liga", "coletor Amazon", "monitor Amazon", "casador (IA)"
MANUTENCAO, VIGIA, ADMIN, NOTIFICADOR = "manutenção", "vigia", "admin", "notificador"
ACESSO = "acesso"


def _problema(
    severidade: Severidade, titulo: str, origem: str, descricao: str, acao: str, exemplo: Dados,
    lembrete: timedelta = DUAS_HORAS,
) -> DefinicaoAviso:
    return DefinicaoAviso(
        severidade, Destino.ADMIN, titulo, origem, descricao, exemplo, agrupa=True, lembrete=lembrete, acao=acao
    )


def _evento(
    severidade: Severidade, titulo: str, origem: str, descricao: str, acao: str | None, exemplo: Dados
) -> DefinicaoAviso:
    return DefinicaoAviso(severidade, Destino.ADMIN, titulo, origem, descricao, exemplo, acao=acao)


F, A, C = Severidade.FALHA, Severidade.ATENCAO, Severidade.CONCLUIDO

CATALOGO: dict[TipoAviso, DefinicaoAviso] = {
    TipoAviso.LIGA_COLETA_CONCLUIDA: _evento(
        C, "Liga · coleta concluída", LIGA, "Fim de uma coleta da LigaMagic sem falha, erro nem desafio.", None,
        Dados(
            titulo_extra="18/10",
            linhas=(
                "Listagens: ok · 20 de 20 categorias · 3 produtos novos",
                "Produtos: ok · 412 ok · 0 falhas",
                "Duração: 1 h 12 min",
            ),
        ),
    ),
    TipoAviso.LIGA_COLETA_PARCIAL: _evento(
        A, "Liga · coleta parcial", LIGA, "Fim de uma coleta da LigaMagic com algumas páginas falhando.",
        "Nada urgente; se repetir, veja Admin → Logs → LigaMagic.",
        Dados(
            titulo_extra="18/10",
            linhas=(
                "Listagens: ok · 20 de 20 categorias · 0 produtos novos",
                "Produtos: parcial · 380 ok · 32 falhas",
                "Duração: 1 h 5 min",
            ),
        ),
    ),
    TipoAviso.LIGA_COLETA_FALHOU: _problema(
        F, "Liga · coleta falhou", LIGA, "Uma etapa da coleta falhou em mais páginas que o limite.",
        "O layout da LigaMagic pode ter mudado: veja Admin → Logs → LigaMagic e os HTMLs na pasta falhas.",
        Dados(linhas=("Etapa: Coleta dos produtos ativos", "Falhas: 300 de 412 produtos")),
    ),
    TipoAviso.LIGA_DESAFIO: _problema(
        F, "Liga · desafio do Cloudflare", LIGA, "A LigaMagic pediu verificação; a coleta fica pausada.",
        "Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.",
        Dados(linhas=("Página: /?view=cards/search&card=categ%3D10", "A coleta fica pausada até você retomar")),
    ),
    TipoAviso.LIGA_PRODUTOS_NOVOS: _evento(
        A, "Liga · produtos novos no catálogo", LIGA, "As listagens trouxeram produtos que não estavam no catálogo.",
        "Ative os que quiser acompanhar em Admin → Catálogo → filtro Novos.",
        Dados(linhas=("3 produtos novos nas listagens",)),
    ),
    TipoAviso.LIGA_INTERROMPIDA: _evento(
        A, "Liga · coleta interrompida", LIGA, "O coletor reiniciou no meio de uma coleta.",
        "A coleta de hoje pode não rodar de novo sozinha: Admin → Serviços → LigaMagic → Rodar agora.",
        Dados(linhas=("2 coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job",)),
    ),
    TipoAviso.LIGA_ERRO: _problema(
        F, "Liga · erro inesperado", LIGA, "Erro inesperado no job ou no meio de uma etapa da coleta.",
        "Veja os logs do coletor (docker compose logs coletor-liga); a próxima coleta tenta de novo.",
        Dados(linhas=("Onde: Coleta dos produtos ativos 41", "Erro: TimeoutError('página não carregou')")),
    ),
    TipoAviso.AMAZON_BUSCA_CONCLUIDA: _evento(
        C, "Amazon · busca concluída", AMAZON, "Fim de um ciclo da busca de anúncios novos sem falha.", None,
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 37 ok · 1 falha", "Duração: 2 h 5 min")),
    ),
    TipoAviso.AMAZON_MONITOR_CONCLUIDO: _evento(
        C, "Amazon · rodada do monitor", MONITOR, "O monitor leu todos os anúncios vencidos (cerca de 4 por hora).",
        None,
        Dados(
            linhas=("Anúncios lidos: 24", "Preços em queda: 2", "Conferências de checkout: 1", "Duração: 14 min")
        ),
    ),
    TipoAviso.AMAZON_BUSCA_PARCIAL: _evento(
        A, "Amazon · busca parcial", AMAZON, "Fim de um ciclo da busca com algumas buscas falhando.",
        "Nada urgente; se repetir, veja Admin → Logs → Amazon.",
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 30 ok · 8 falhas", "Duração: 2 h 10 min")),
    ),
    TipoAviso.AMAZON_BUSCA_FALHOU: _problema(
        F, "Amazon · busca falhou", AMAZON, "Um ciclo da busca falhou em mais buscas que o limite.",
        "O layout da Amazon pode ter mudado: veja Admin → Logs → Amazon e os HTMLs na pasta falhas.",
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 12 ok · 26 falhas", "Duração: 1 h 40 min")),
    ),
    TipoAviso.AMAZON_CAPTCHA: _problema(
        F, "Amazon · CAPTCHA", AMAZON, "A Amazon pediu verificação; busca, monitor e conferência ficam pausados.",
        "Resolva no noVNC da Amazon (porta 6081) e depois Admin → Serviços → Amazon → Retomar.",
        Dados(
            linhas=(
                "Página: /s?k=aetherdrift+commander",
                "Busca, monitor e conferência pausados até você retomar",
                (
                    "Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
                    "senão confira à mão"
                ),
            )
        ),
    ),
    TipoAviso.AMAZON_SEM_LOGIN: _problema(
        F, "Amazon · conta sem login", AMAZON, "A conferência de checkout caiu no login; o monitor continua.",
        "Faça login na conta Amazon pelo noVNC da Amazon (porta 6081) e depois "
        "Admin → Serviços → Amazon → Retomar conferência.",
        Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",)),
    ),
    TipoAviso.AMAZON_CARRINHO: _problema(
        F, "Amazon · conferir o carrinho", AMAZON,
        "O coletor não pôde tirar sozinho o item de uma conferência do carrinho (um aviso por ASIN).",
        "Confira o carrinho pelo noVNC da Amazon (porta 6081), tire o item se não for seu e "
        "clique em Admin → Serviços → Já conferi.",
        Dados(
            titulo_extra="B0DNV55QBS",
            linhas=(
                "Pode haver 1× B0DNV55QBS de uma conferência automática no carrinho",
                "Motivo: carrinho com outros itens (B0AAAA0001)",
            ),
        ),
    ),
    TipoAviso.AMAZON_PAUSADA: _problema(
        F, "Amazon · pausada", AMAZON, "A Amazon foi pausada por páginas com falha ou erros inesperados seguidos.",
        "Veja os logs (docker compose logs coletor-amazon) e depois Admin → Serviços → Amazon → Retomar.",
        Dados(
            linhas=(
                "Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)",
                "Com a Amazon pausada, a retirada automática de item do carrinho também para",
            )
        ),
    ),
    TipoAviso.AMAZON_ERRO: _problema(
        A, "Amazon · erro inesperado", AMAZON, "Erro inesperado num passo da varredura; tenta de novo em 15 min.",
        "Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).",
        Dados(linhas=("Erro: RuntimeError('navegador fechou')",)),
    ),
    TipoAviso.AMAZON_INTERROMPIDA: _evento(
        A, "Amazon · ciclo interrompido", AMAZON, "O coletor da Amazon reiniciou no meio de um ciclo.",
        "Nada a fazer: a fila continua sozinha.",
        Dados(linhas=("1 ciclo(s) marcado(s) como falha: o coletor reiniciou",)),
    ),
    TipoAviso.IA_RODADA_CONCLUIDA: _evento(
        C, "IA · rodada concluída", IA, "Rodada do casador que avaliou pelo menos um anúncio.", None,
        Dados(
            linhas=(
                "Avaliados: 12",
                "Confirmados pelo automático: 3",
                "Ignorados pelo automático: 5",
                "Esperando você: 4",
            ),
            acao="Revise os pendentes em Admin → Casamentos.",
        ),
    ),
    TipoAviso.IA_PAUSADA: _problema(
        F, "IA · casador pausado", IA, "A OpenAI recusou a chave ou a configuração; o casador fica pausado.",
        "Corrija a chave da OpenAI (.env) ou Admin → Configurações → IA e depois "
        "Admin → Serviços → Casador → Retomar.",
        Dados(linhas=("Motivo: chave recusada pela OpenAI (401)",)),
    ),
    TipoAviso.IA_SEM_ORCAMENTO: _problema(
        A, "IA · sem orçamento", IA, "O teto de gasto ou de chamadas do dia (ou do mês) foi atingido.",
        "Volta sozinho no próximo período, ou suba o teto em Admin → Configurações → IA.",
        Dados(titulo_extra="dia 18/10", linhas=("Motivo: teto diário de US$ 1,00 atingido",)),
    ),
    TipoAviso.IA_FALHAS_SEGUIDAS: _problema(
        A, "IA · falhas seguidas", IA, "Chamadas seguidas à OpenAI falharam e a rodada parou.",
        "Nada a fazer se for passageiro: a próxima rodada tenta de novo.",
        Dados(linhas=("3 chamadas seguidas falharam; a rodada parou", "Última: OpenAI 503")),
    ),
    TipoAviso.BACKUP_CONCLUIDO: _evento(
        C, "Backup · concluído", MANUTENCAO, "Backup diário do banco feito (e limpeza do histórico).", None,
        Dados(
            titulo_extra="18/10",
            linhas=("Tamanho: 607,3 KB", "Cópia no R2: sim", "Linhas antigas apagadas: 1.234"),
        ),
    ),
    TipoAviso.BACKUP_ERRO: _problema(
        F, "Backup · erro", MANUTENCAO, "O backup, a cópia no R2 ou a limpeza falhou.",
        "Tenta de novo amanhã às 04:00; veja Admin → Logs → Manutenção.",
        Dados(
            titulo_extra="18/10",
            linhas=("Erro: envio ao R2 falhou: EndpointConnectionError", "O backup local ficou salvo"),
        ),
    ),
    TipoAviso.BACKUP_INTERROMPIDO: _evento(
        A, "Backup · interrompido", MANUTENCAO, "O serviço de manutenção reiniciou no meio de um backup.",
        "Nada a fazer: o backup do dia roda de novo.",
        Dados(linhas=("1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)),
    ),
    TipoAviso.SERVICO_SEM_SINAL: _problema(
        F, "Serviço sem sinal", VIGIA, "Um serviço ativo ficou mais de 10 min sem dar sinal de vida.",
        "Veja se o container está de pé (docker compose ps) e os logs dele.",
        Dados(titulo_extra="coletor-amazon", linhas=("Último sinal: 18/10 10:30 (há 12 min)",)),
    ),
    TipoAviso.SERVICO_PAUSADO_MANUAL: _evento(
        A, "Serviço mudou no admin", ADMIN, "Alguém pausou ou retomou um serviço em Admin → Serviços.", None,
        Dados(titulo_extra="Amazon", linhas=("Novo estado: pausado",)),
    ),
    TipoAviso.MENSAGEM_NAO_ENVIADA: _problema(
        F, "WhatsApp · mensagem não enviada", NOTIFICADOR,
        "Uma mensagem falhou de vez (5 recusas). No máximo um aviso por hora.",
        "Confira a instância e os grupos em Admin → Configurações → Geral e reenvie em Admin → Mensagens.",
        Dados(linhas=("#123 para oportunidades: HTTP 400: grupo não encontrado",)),
        lembrete=timedelta(hours=1),
    ),
    TipoAviso.OPORTUNIDADE: DefinicaoAviso(
        Severidade.OPORTUNIDADE, Destino.OPORTUNIDADES, "Oportunidade", MONITOR,
        "Oferta confirmada da Amazon abaixo da Liga (regras do motor), no grupo de oportunidades.",
        Dados(
            titulo_extra="18% abaixo da Liga",
            destaque="Final Fantasy - Caixa de Booster de Jogo",
            linhas=(
                ("Amazon: ", Negrito("R$ 1.299,90"), " (conferido; frete à parte)"),
                "Vendido por: Amazon · Prime",
                "Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00",
            ),
            link_produto="https://www.amazon.com.br/dp/B0TESTE123",
        ),
    ),
    TipoAviso.CODIGO_ACESSO: DefinicaoAviso(
        Severidade.ACESSO, Destino.INDIVIDUAL, "Código de acesso", ACESSO,
        "Código de 6 dígitos para entrar no site, mandado só para o número da pessoa (vale 5 min). "
        "Desligado, ninguém recebe código: fica só o acesso de emergência pelo terminal.",
        Dados(destaque="123456", linhas=("Vale por 5 minutos.", "Não passe este código para ninguém.")),
    ),
    TipoAviso.SEGURANCA_USUARIO: _evento(
        A, "Segurança · acesso alterado", ACESSO,
        "Usuário criado, papel alterado, usuário desativado ou reativado, ou permissão de um papel alterada.",
        "Se não foi alguém do grupo, desative o usuário em Gestão → Usuários.",
        Dados(
            titulo_extra="papel alterado",
            linhas=("Usuário: Pessoa Exemplo", "Papel: Grupo → Operador", "Por: Pessoa Admin"),
        ),
    ),
    TipoAviso.SEGURANCA_LIMITE: _problema(
        A, "Segurança · limite de códigos", ACESSO,
        "Pedidos de código acima do limite (3 por número em 15 min ou 20 por hora no total) ou 5 códigos errados "
        "seguidos (o código é invalidado); agrupa por número. Resolve quando o número entra no site (o limite "
        "total, quando um pedido volta a ser aceito).",
        "Se ninguém do grupo está tentando entrar, alguém pode estar testando números; "
        "o site recusa novos pedidos até a janela passar.",
        Dados(linhas=("Limite: 3 códigos por número em 15 min", "Número com final 34")),
    ),
}
