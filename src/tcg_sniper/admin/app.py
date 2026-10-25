import re
import secrets
from datetime import datetime, time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.admin import consultas, consultas_amazon, estilo
from tcg_sniper.admin import formularios_config as form_cfg
from tcg_sniper.admin import formularios_ia as form_ia
from tcg_sniper.admin.icones import icone
from tcg_sniper.avisos import formato
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, EMOJI, TipoAviso
from tcg_sniper.coletor_amazon.asin import LinkInvalido, extrair_asin
from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, ROTULOS, aplicar_config, validar_config
from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.coletor_liga.esfriamento import situacao_desafio
from tcg_sniper.config import CATEGORIAS_SELADOS, Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.consultas import historico
from tcg_sniper.consultas import mensagens as consultas_mensagens
from tcg_sniper.consultas import menu as consultas_menu
from tcg_sniper.consultas import painel as consultas_painel
from tcg_sniper.consultas.casamentos import (
    EXPLICACAO_REAVALIAR,
    MENSAGENS_CASAMENTO,
    SITUACOES_CASAMENTO,
    buscar_produtos,
    casador_parado,
    detalhe_casamento,
    sugestoes_para,
)
from tcg_sniper.consultas.catalogo import SITUACOES_PRODUTO
from tcg_sniper.consultas.catalogo_gestao import FILTROS, alterar_ativo_em_lote, alternar_ativo, buscar_catalogo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_CASADOR,
    COLETOR_MANUTENCAO,
    COLETOR_NOTIFICADOR,
    AnuncioAmazon,
    EstadoColetorTipo,
    OrigemCasamento,
    ProdutoLiga,
    TipoColeta,
)
from tcg_sniper.formatacao import formatar_brl, formatar_bytes
from tcg_sniper.gestao import servicos as acoes
from tcg_sniper.gestao.servicos import Servico
from tcg_sniper.manutencao.servico import HORA_BACKUP
from tcg_sniper.notificador.base import Destino
from tcg_sniper.oportunidades import motor

SENHA_PADRAO = "trocar-esta-senha"
MENSAGEM_LOTE = re.compile(r"\d{1,9} produto\(s\) (ativado|desativado)\(s\)\.")

MENSAGEM_AVISOS = "Salvo; vale a partir do próximo aviso."


ROTULOS_DESTINO = {
    Destino.ADMIN: "grupo admin",
    Destino.OPORTUNIDADES: "grupo oportunidades",
    Destino.INDIVIDUAL: "só para a pessoa",
}


ABAS_LOGS = ("liga", "amazon", "monitor", "checkout", "ia", "manutencao")


def com_mensagem(destino: str, chave: str) -> str:
    """Acrescenta `msg=<chave>` ao destino (que pode já ter parâmetros)."""
    return destino + ("&" if "?" in destino else "?") + urlencode({"msg": chave})


def destino_seguro(voltar: str, prefixo: str = "/casamentos") -> str:
    """Só volta para telas do próprio admin que começam com `prefixo` (nunca para fora)."""
    if voltar.startswith(prefixo) and not voltar.startswith("//") and "\\" not in voltar:
        return voltar
    return prefixo


def numero_pagina(texto: str) -> int:
    """Número de página vindo da URL; texto inválido ou gigante vale 1 (nunca 500)."""
    texto = texto.strip()
    return int(texto) if texto.isdecimal() and len(texto) <= 9 else 1


def formatar_data(dt: datetime | None, zona: ZoneInfo) -> str:
    return "" if dt is None else dt.astimezone(zona).strftime("%d/%m/%Y %H:%M")


def duracao(inicio: datetime, fim: datetime | None) -> str:
    """Duração de uma coleta em minutos ("18 min"); "—" enquanto não terminou."""
    if fim is None:
        return "—"
    minutos = int((fim - inicio).total_seconds() // 60)
    return f"{minutos} min" if minutos >= 1 else "< 1 min"


async def ler_formulario(request: Request) -> dict[str, str]:
    """Corpo urlencoded lido à mão: evita a dependência python-multipart só para os formulários."""
    campos = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    return {nome: valores[0] for nome, valores in campos.items()}


def criar_app(sessoes: sessionmaker[Session], config: Config) -> FastAPI:
    senha = config.admin_senha
    if not senha.strip() or senha == SENHA_PADRAO:
        raise ValueError(
            "ADMIN_SENHA não definida: configure uma senha própria para o admin "
            "(vazia ou o valor padrão 'trocar-esta-senha' não são aceitos)"
        )
    seguranca = HTTPBasic()

    def autenticar(credenciais: Annotated[HTTPBasicCredentials, Depends(seguranca)]) -> None:
        if not secrets.compare_digest(credenciais.password.encode(), config.admin_senha.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    def config_da_requisicao(request: Request) -> None:
        """Configuração efetiva (.env + tela) desta requisição, em `request.state.config`."""
        request.state.config = carregar_config(sessoes, config)
        with sessoes() as s, s.begin():
            request.state.menu = consultas_menu.contadores_menu(s, repo.agora_utc())

    app = FastAPI(title="TCG Sniper", dependencies=[Depends(autenticar), Depends(config_da_requisicao)])
    # os arquivos estáticos não passam pela senha do admin; são só CSS e ícones
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.globals["icone"] = icone
    templates.env.globals["versao_css"] = (estilo.hash_gravado() or "0")[:12]
    templates.env.filters["brl"] = formatar_brl
    # Preço conferido de uma conferência (itens + impostos, SEM o frete; regra do usuário).
    templates.env.globals["valor_conferido"] = lambda c: motor.preco_conferido(c.itens, c.impostos, c.total, c.frete)
    templates.env.filters["usd"] = lambda v: f"US$ {v:.2f}".replace(".", ",")
    templates.env.filters["usd4"] = lambda v: f"US$ {v:.4f}".replace(".", ",")
    templates.env.filters["duracao"] = duracao
    templates.env.filters["tamanho"] = formatar_bytes
    templates.env.filters["milhar"] = lambda n: f"{n:,}".replace(",", ".")
    templates.env.filters["envio"] = lambda envio, vendedor=None: {
        "amazon": "vendido pela Amazon",
        "fba": f"vendido por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}, enviado pela Amazon",
        "proprio": f"vendido e enviado por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}",
    }.get(envio.value, "—")

    @pass_context
    def _data(contexto, dt):
        return formatar_data(dt, contexto["request"].state.config.zona)

    templates.env.filters["data"] = _data

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        efetiva = request.state.config
        agora = repo.agora_utc()
        chave_ia = bool((config.openai_api_key or "").strip())
        with sessoes() as s, s.begin():
            pausado = repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado is not EstadoColetorTipo.ATIVO
            resumo = consultas_mensagens.resumo(s, agora, notificador_pausado=pausado)
            servicos_ = consultas_painel.saude_servicos(s, agora, efetiva, chave_ia, resumo)
            backup = consultas_painel.saude_backup(s, agora, efetiva)
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "avisos": consultas_painel.avisos(s, agora, efetiva, servicos_, resumo)
                    + consultas_painel.avisos_backup(backup),
                    "servicos": [*servicos_, backup],
                    "n": consultas_painel.numeros(s, agora, efetiva),
                    "atividade": consultas_painel.atividade_hoje(s, agora, efetiva),
                    "atualizado": agora.astimezone(efetiva.zona).strftime("%H:%M"),
                },
            )

    @app.get("/logs", response_class=HTMLResponse)
    def logs(
        request: Request,
        aba: str = "liga",
        liga_status: str = "todos",
        liga_pagina: str = "1",
        amazon_status: str = "todos",
        amazon_pagina: str = "1",
        situacao: str = "todas",
        finalidade: str = "todas",
        ia_pagina: str = "1",
        monitor_pagina: str = "1",
        checkout_situacao: str = "todas",
        checkout_pagina: str = "1",
        manutencao_pagina: str = "1",
    ):
        if aba not in ABAS_LOGS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"aba inválida: {aba}")
        for valor in (liga_status, amazon_status):
            if valor not in historico.STATUS_HISTORICO:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status inválido: {valor}")
        if situacao not in historico.SITUACOES_IA:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
        if finalidade not in historico.FINALIDADES_IA:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"finalidade inválida: {finalidade}")
        if checkout_situacao not in historico.SITUACOES_CHECKOUT:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {checkout_situacao}")
        with sessoes() as s, s.begin():
            coletas, pagina_liga, paginas_liga = historico.historico_coletas(
                s, TIPOS_LIGA, liga_status, numero_pagina(liga_pagina)
            )
            ciclos, pagina_amazon, paginas_amazon = historico.historico_coletas(
                s, (TipoColeta.AMAZON,), amazon_status, numero_pagina(amazon_pagina)
            )
            chamadas, pagina_ia, paginas_ia = historico.historico_chamadas_ia(
                s, situacao, finalidade, numero_pagina(ia_pagina)
            )
            # A consulta do monitor (agrupa todas as ofertas lidas) só roda na própria aba.
            leituras, pagina_monitor, paginas_monitor = None, numero_pagina(monitor_pagina), 1
            if aba == "monitor":
                leituras, pagina_monitor, paginas_monitor = historico.historico_monitor(s, pagina_monitor)
            conferencias, pagina_checkout, paginas_checkout = historico.historico_conferencias(
                s, checkout_situacao, numero_pagina(checkout_pagina)
            )
            execucoes, pagina_manutencao, paginas_manutencao = historico.historico_manutencao(
                s, numero_pagina(manutencao_pagina)
            )
            parametros = {
                "aba": aba,
                "liga_status": liga_status,
                "liga_pagina": pagina_liga,
                "amazon_status": amazon_status,
                "amazon_pagina": pagina_amazon,
                "situacao": situacao,
                "finalidade": finalidade,
                "ia_pagina": pagina_ia,
                "monitor_pagina": pagina_monitor,
                "checkout_situacao": checkout_situacao,
                "checkout_pagina": pagina_checkout,
                "manutencao_pagina": pagina_manutencao,
            }

            def link(**mudancas) -> str:
                return "/logs?" + urlencode({**parametros, **mudancas})

            return templates.TemplateResponse(
                request,
                "logs.html",
                {
                    "aba": aba,
                    "parametros": parametros,
                    "link": link,
                    "coletas": coletas,
                    "ciclos": ciclos,
                    "chamadas": chamadas,
                    "pagina_liga": pagina_liga,
                    "paginas_liga": paginas_liga,
                    "pagina_amazon": pagina_amazon,
                    "paginas_amazon": paginas_amazon,
                    "pagina_ia": pagina_ia,
                    "paginas_ia": paginas_ia,
                    "leituras": leituras,
                    "pagina_monitor": pagina_monitor,
                    "paginas_monitor": paginas_monitor,
                    "conferencias": conferencias,
                    "pagina_checkout": pagina_checkout,
                    "paginas_checkout": paginas_checkout,
                    "execucoes": execucoes,
                    "pagina_manutencao": pagina_manutencao,
                    "paginas_manutencao": paginas_manutencao,
                    "checkout_situacao": checkout_situacao,
                    "situacoes_checkout": historico.SITUACOES_CHECKOUT,
                    "liga_status": liga_status,
                    "amazon_status": amazon_status,
                    "situacao": situacao,
                    "finalidade": finalidade,
                    "status_historico": historico.STATUS_HISTORICO,
                    "situacoes_ia": historico.SITUACOES_IA,
                    "finalidades_ia": historico.FINALIDADES_IA,
                },
            )

    @app.get("/servicos", response_class=HTMLResponse)
    def servicos(request: Request, msg: str = ""):
        efetiva = request.state.config
        with sessoes() as s, s.begin():
            cfg_amazon = repo_amz.obter_config(s)
            agora = repo.agora_utc()
            monitor = repo_amz.situacao_monitor(s, agora, cfg_amazon)
            lenta_ha_horas = (
                max(1, round((agora - monitor.mais_antiga_lenta).total_seconds() / 3600)) if monitor.mais_antiga_lenta else None
            )
            desafio = situacao_desafio(s, repo.agora_utc(), efetiva.zona, efetiva.esfriar_desafio_min)
            return templates.TemplateResponse(
                request,
                "servicos.html",
                {
                    "liga_parada": desafio.parada_hoje,
                    "liga_esfriando_ate": (
                        f"{desafio.esfriando_ate.astimezone(efetiva.zona):%H:%M}" if desafio.esfriando_ate else None
                    ),
                    "estado": repo.obter_estado(s),
                    "em_andamento": historico.coleta_em_andamento(s, TIPOS_LIGA),
                    "ultima_liga": historico.ultima_coleta_sucesso(s, TIPOS_LIGA),
                    "coleta_hora": efetiva.coleta_hora.strftime("%H:%M"),
                    "coleta_jitter": efetiva.coleta_jitter_min,
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "estado_amazon_busca": repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA),
                    "ciclo_amazon": historico.ciclo_atual(s),
                    "janela": (f"{cfg_amazon.janela_inicio:%H:%M}", f"{cfg_amazon.janela_fim:%H:%M}"),
                    "cfg_amazon": cfg_amazon,
                    "a_conferir_a_mao": repo_amz.conferencias_a_conferir_a_mao(s),
                    "janela_monitor": (f"{cfg_amazon.monitor_janela_inicio:%H:%M}", f"{cfg_amazon.monitor_janela_fim:%H:%M}"),
                    "monitor": monitor,
                    "lenta_ha_horas": lenta_ha_horas,
                    "estado_casador": repo.obter_estado(s, coletor=COLETOR_CASADOR),
                    "cfg_ia": repo_ia.obter_config_ia(s),
                    "ia_chave": bool((config.openai_api_key or "").strip()),
                    "host": efetiva.host_publico,
                    "mensagem": acoes.MENSAGENS.get(msg),
                    "estado_notificador": repo.obter_estado(s, coletor=COLETOR_NOTIFICADOR),
                    "notificador": consultas_mensagens.estado_notificador(s, repo.agora_utc()),
                    "estado_manutencao": repo.obter_estado(s, coletor=COLETOR_MANUTENCAO),
                    "processo_manutencao": consultas_painel.processo_manutencao(s, repo.agora_utc()),
                    "backup_ok": repo_man.ultima_ok(s),
                    "backup_ultima": repo_man.ultima(s),
                    "hora_backup": f"{HORA_BACKUP:%H:%M}",
                    "r2": config.r2_configurado,
                },
            )

    def _redirecionar(msg: str) -> RedirectResponse:
        return RedirectResponse(f"/servicos?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

    def _ligar(servico: Servico) -> RedirectResponse:
        with sessoes() as s, s.begin():
            msg = acoes.ligar(s, servico, repo.agora_utc())
        return _redirecionar(msg)

    def _desligar(servico: Servico) -> RedirectResponse:
        with sessoes() as s, s.begin():
            msg = acoes.desligar(s, servico, repo.agora_utc())
        return _redirecionar(msg)

    def _ajustar_amazon(chave: Literal["monitor_ligado", "checkout_ligado"], ligado: bool) -> RedirectResponse:
        with sessoes() as s, s.begin():
            msg = acoes.ajustar_amazon(s, chave, ligado, repo.agora_utc())
        return _redirecionar(msg)

    @app.post("/retomar")
    def retomar(request: Request):
        efetiva = request.state.config
        with sessoes() as s, s.begin():
            msg = acoes.retomar_desafio(s, Servico.LIGA, efetiva.zona, efetiva, repo.agora_utc())
        return _redirecionar(msg)

    @app.post("/rodar-agora")
    def rodar_agora(request: Request):
        """Respeita o esfriamento (o pedido espera) e a parada do 2º desafio (nada é pedido)."""
        efetiva = request.state.config
        with sessoes() as s, s.begin():
            msg = acoes.rodar_agora(s, Servico.LIGA, efetiva.zona, efetiva, repo.agora_utc())
        return _redirecionar(msg)

    @app.post("/liga/pausar")
    def pausar_liga():
        return _desligar(Servico.LIGA)

    @app.post("/liga/retomar")
    def retomar_liga():
        return _ligar(Servico.LIGA)

    @app.post("/notificador/pausar")
    def pausar_notificador():
        return _desligar(Servico.WHATSAPP)

    @app.post("/notificador/retomar")
    def retomar_notificador():
        return _ligar(Servico.WHATSAPP)

    @app.post("/manutencao/pausar")
    def pausar_manutencao():
        return _desligar(Servico.BACKUP)

    @app.post("/manutencao/retomar")
    def retomar_manutencao():
        return _ligar(Servico.BACKUP)

    @app.post("/amazon/pausar")
    def pausar_amazon():
        return _desligar(Servico.AMAZON_MONITOR)

    @app.post("/amazon/retomar")
    def retomar_amazon():
        return _ligar(Servico.AMAZON_MONITOR)

    @app.post("/amazon/busca/pausar")
    def pausar_busca_amazon():
        return _desligar(Servico.AMAZON_BUSCA)

    @app.post("/amazon/busca/retomar")
    def retomar_busca_amazon():
        return _ligar(Servico.AMAZON_BUSCA)

    @app.post("/amazon/monitor/ligar")
    def ligar_monitor():
        return _ajustar_amazon("monitor_ligado", True)

    @app.post("/amazon/monitor/desligar")
    def desligar_monitor():
        return _ajustar_amazon("monitor_ligado", False)

    @app.post("/amazon/checkout/ligar")
    def ligar_checkout():
        return _ajustar_amazon("checkout_ligado", True)

    @app.post("/amazon/checkout/desligar")
    def desligar_checkout():
        return _ajustar_amazon("checkout_ligado", False)

    @app.post("/amazon/checkout/retomar")
    def retomar_checkout():
        with sessoes() as s, s.begin():
            msg = acoes.retomar_checkout(s, repo.agora_utc())
        return _redirecionar(msg)

    @app.post("/amazon/carrinho/{conferencia_id}/conferido")
    def carrinho_conferido(conferencia_id: int):
        """"Já conferi": o usuário viu o carrinho pelo noVNC; a conferência sai do "conferir à mão" e o
        aviso do carrinho daquele ASIN fecha."""
        with sessoes() as s, s.begin():
            resolvida = acoes.carrinho_conferido(s, conferencia_id, repo.agora_utc())
        if not resolvida:  # inexistente ou fora do "conferir à mão": não marca nada
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conferência não está aguardando conferência à mão")
        return _redirecionar("carrinho_conferido")

    @app.post("/casador/pausar")
    def pausar_casador():
        return _desligar(Servico.CASADOR)

    @app.post("/casador/retomar")
    def retomar_casador():
        return _ligar(Servico.CASADOR)

    @app.post("/casador/rodar-agora")
    def rodar_casador(request: Request):
        efetiva = request.state.config
        with sessoes() as s, s.begin():
            msg = acoes.rodar_agora(s, Servico.CASADOR, efetiva.zona, efetiva, repo.agora_utc())
        return _redirecionar(msg)

    MENSAGEM_CONFIG = "Salvo; vale a partir da próxima coleta ou ciclo."

    @app.get("/mensagens", response_class=HTMLResponse)
    def mensagens(request: Request, situacao: str = "todas", destino: str = "todos", pagina: str = "1"):
        if situacao not in consultas_mensagens.SITUACOES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
        if destino not in consultas_mensagens.DESTINOS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"destino inválido: {destino}")
        with sessoes() as s, s.begin():
            linhas, pagina_atual, paginas = consultas_mensagens.listar(s, situacao, destino, numero_pagina(pagina))
            parametros = {"situacao": situacao, "destino": destino, "pagina": pagina_atual}

            def link(**mudancas) -> str:
                return "/mensagens?" + urlencode({**parametros, **mudancas})

            return templates.TemplateResponse(
                request,
                "mensagens.html",
                {
                    "linhas": linhas,
                    "situacao": situacao,
                    "destino": destino,
                    "situacoes": consultas_mensagens.SITUACOES,
                    "destinos": consultas_mensagens.DESTINOS,
                    "pagina": pagina_atual,
                    "paginas": paginas,
                    "link": link,
                    "aqui": link(),
                },
            )

    @app.post("/mensagens/{mensagem_id}")
    async def acao_mensagem(request: Request, mensagem_id: int):
        if not 1 <= mensagem_id <= 2**31 - 1:  # fora do integer do Postgres
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mensagem não encontrada")
        formulario = await ler_formulario(request)
        acoes = {"reenviar": repo_msg.reenviar, "descartar": repo_msg.descartar}
        acao = acoes.get(formulario.get("acao", ""))
        if acao is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ação inválida")
        try:
            with sessoes() as s, s.begin():
                acao(s, mensagem_id, repo.agora_utc())
        except repo_msg.MensagemNaoEncontrada:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mensagem não encontrada") from None
        except repo_msg.AcaoInvalida as erro:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erro)) from None
        voltar = destino_seguro(formulario.get("voltar", "/mensagens"), "/mensagens")
        return RedirectResponse(voltar, status_code=status.HTTP_303_SEE_OTHER)

    def _texto(valor) -> str:
        if valor is None:
            return ""
        if isinstance(valor, time):
            return valor.strftime("%H:%M")
        if isinstance(valor, float):
            return f"{valor:g}"
        return str(valor)

    def _salvos() -> dict[str, dict[str, str]]:
        with sessoes() as s, s.begin():
            geral = repo.obter_config_geral(s, config)
            liga = repo.obter_config_liga(s, config)
            amazon = repo_amz.obter_config(s)
            ia = repo_ia.obter_config_ia(s)
            return {
                "geral": {c: _texto(getattr(geral, c)) for c in form_cfg.CAMPOS_GERAL},
                "liga": {c: _texto(getattr(liga, c)) for c in form_cfg.CAMPOS_LIGA},
                "amazon": {c: _texto(getattr(amazon, c)) for c in CAMPOS},
                "ia": {c: form_ia.texto_ia(ia, c) for c in form_ia.CAMPOS_IA},
            }

    def _resumo_ia(request: Request) -> dict:
        with sessoes() as s, s.begin():
            cfg = repo_ia.obter_config_ia(s)
            g = repo_ia.gasto(s, repo.agora_utc(), request.state.config.zona)
            return {
                "gasto": g,
                "teto_dia": cfg.teto_dia_usd,
                "teto_mes": cfg.teto_mes_usd,
                "max_chamadas": cfg.max_chamadas_dia,
                "chave": bool((config.openai_api_key or "").strip()),
            }

    def _avisos_da_tela(request: Request) -> list[dict]:
        zona = request.state.config.zona
        agora = repo.agora_utc()
        with sessoes() as s:
            estados = avisos.ligados(s)
        return [
            {
                "tipo": tipo.value,
                "titulo": d.titulo,
                "emoji": EMOJI[d.severidade],
                "severidade": d.severidade.value,
                "grupo": ROTULOS_DESTINO[d.grupo],
                "descricao": d.descricao,
                "agrupa": d.agrupa,
                "exemplo": formato.formatar(formato.aviso_de(tipo, d.exemplo, agora), zona, estrito=False),
                "ligado": estados[tipo],
            }
            for tipo, d in CATALOGO.items()
        ]

    def _tela_configuracoes(
        request: Request,
        msg: str = "",
        secao: str = "",
        secao_com_erro: str | None = None,
        digitados: dict[str, str] | None = None,
        erros: dict[str, str] | None = None,
    ):
        valores = _salvos()
        if secao_com_erro is not None:
            valores[secao_com_erro] = digitados or {}
        secoes = [
            ("geral", "Geral", form_cfg.CAMPOS_GERAL, form_cfg.ROTULOS_GERAL, form_cfg.EXPLICACOES_GERAL),
            ("liga", "LigaMagic", form_cfg.CAMPOS_LIGA, form_cfg.ROTULOS_LIGA, form_cfg.EXPLICACOES_LIGA),
            ("amazon", "Amazon", CAMPOS, ROTULOS, EXPLICACOES),
            ("ia", "IA", form_ia.CAMPOS_IA, form_ia.ROTULOS_IA, form_ia.EXPLICACOES_IA),
        ]
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "secoes": [
                    {
                        "id": id_,
                        "titulo": titulo,
                        "campos": campos,
                        "rotulos": rotulos,
                        "explicacoes": explicacoes,
                        "valores": valores[id_],
                        "erros": (erros or {}) if id_ == secao_com_erro else {},
                        "opcoes": form_ia.OPCOES_IA if id_ == "ia" else {},
                    }
                    for id_, titulo, campos, rotulos, explicacoes in secoes
                ],
                "avisos": _avisos_da_tela(request),
                "mensagem": (
                    MENSAGEM_AVISOS
                    if msg == "avisos"
                    else MENSAGEM_CONFIG if msg in ("geral", "liga", "amazon", "ia") else None
                ),
                "resumo_ia": _resumo_ia(request),
                "categorias_padrao": ",".join(CATEGORIAS_SELADOS),
                "secao_ativa": secao_com_erro or (
                    msg if msg in ("geral", "liga", "amazon", "ia", "avisos")
                    else secao if secao in ("geral", "liga", "amazon", "ia", "avisos") else "geral"
                ),
            },
            status_code=status.HTTP_400_BAD_REQUEST if secao_com_erro else status.HTTP_200_OK,
        )

    @app.post("/configuracoes/avisos")
    async def salvar_aviso(request: Request):
        formulario = await ler_formulario(request)
        try:
            tipo = TipoAviso(formulario.get("tipo", ""))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "tipo de aviso desconhecido") from None
        with sessoes() as s, s.begin():
            avisos.definir_ligado(s, tipo, formulario.get("ligado") == "1")
        return RedirectResponse("/configuracoes?msg=avisos", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/configuracoes", response_class=HTMLResponse)
    def configuracoes(request: Request, msg: str = "", secao: str = ""):
        return _tela_configuracoes(request, msg, secao)

    async def _salvar_secao(request: Request, secao: str, campos, validar, gravar):
        formulario = await ler_formulario(request)
        valores, erros = validar(formulario)
        if erros:
            digitados = {campo: formulario.get(campo, "") for campo in campos}
            return _tela_configuracoes(request, secao_com_erro=secao, digitados=digitados, erros=erros)
        with sessoes() as s, s.begin():
            gravar(s, valores)
        return RedirectResponse(f"/configuracoes?msg={secao}", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/configuracoes/geral", response_class=HTMLResponse)
    async def salvar_geral(request: Request):
        def gravar(s, valores):
            repo.obter_config_geral(s, config)
            repo.salvar_config_geral(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "geral", form_cfg.CAMPOS_GERAL, form_cfg.validar_geral, gravar)

    @app.post("/configuracoes/liga", response_class=HTMLResponse)
    async def salvar_liga(request: Request):
        def gravar(s, valores):
            repo.obter_config_liga(s, config)
            repo.salvar_config_liga(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "liga", form_cfg.CAMPOS_LIGA, form_cfg.validar_liga, gravar)

    @app.post("/configuracoes/amazon", response_class=HTMLResponse)
    async def salvar_amazon(request: Request):
        def gravar(s, valores):
            aplicar_config(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "amazon", CAMPOS, validar_config, gravar)

    @app.post("/configuracoes/ia", response_class=HTMLResponse)
    async def salvar_ia(request: Request):
        def gravar(s, valores):
            repo_ia.salvar_config_ia(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "ia", form_ia.CAMPOS_IA, form_ia.validar_ia, gravar)

    @app.get("/catalogo", response_class=HTMLResponse)
    def catalogo(
        request: Request,
        busca: str = "",
        filtro: str = "todos",
        categoria: str = "",
        com_preco: str = "",
        pagina: str = "1",
        msg: str = "",
    ):
        if filtro not in FILTROS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        texto_pagina = pagina.strip()
        # Limite de dígitos: int() de um número gigante estoura (ValueError/500); acima disso vale 1.
        numero = int(texto_pagina) if texto_pagina.isdecimal() and len(texto_pagina) <= 9 else 1
        numero = max(numero, 1)
        so_com_preco = com_preco == "1"
        with sessoes() as s, s.begin():
            categorias = consultas.listar_categorias(s)
            if categoria and categoria not in categorias:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            linhas, total, numero, paginas = buscar_catalogo(
                s, busca, filtro, repo.agora_utc(), categoria or None, so_com_preco, numero
            )
            parametros = {"busca": busca, "filtro": filtro, "categoria": categoria}
            if so_com_preco:
                parametros["com_preco"] = "1"
            parametros = {k: v for k, v in parametros.items() if v and not (k == "filtro" and v == "todos")}

            def link(destino: int) -> str:
                return "/catalogo?" + urlencode({**parametros, "pagina": destino})

            return templates.TemplateResponse(
                request,
                "catalogo.html",
                {
                    "linhas": linhas,
                    "total": total,
                    "pagina": numero,
                    "paginas": paginas,
                    "link": link,
                    "link_anterior": link(numero - 1) if numero > 1 else None,
                    "link_proxima": link(numero + 1) if numero < paginas else None,
                    "busca": busca,
                    "filtro": filtro,
                    "filtros": FILTROS,
                    "categoria": categoria,
                    "categorias": categorias,
                    "com_preco": so_com_preco,
                    "mensagem": msg if MENSAGEM_LOTE.fullmatch(msg) else None,
                },
            )

    @app.post("/catalogo/lote")
    async def alterar_lote(request: Request):
        formulario = await ler_formulario(request)
        acao, busca = formulario.get("acao", ""), formulario.get("busca", "")
        categoria, com_preco = formulario.get("categoria", ""), formulario.get("com_preco", "")
        filtro = formulario.get("filtro", "todos")
        if acao not in ("ativar", "desativar"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        if filtro not in FILTROS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        ativar = acao == "ativar"
        so_com_preco = com_preco == "1"
        with sessoes() as s, s.begin():
            if categoria and categoria not in consultas.listar_categorias(s):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            alterados = alterar_ativo_em_lote(
                s, ativar, busca, filtro, categoria or None, so_com_preco, repo.agora_utc()
            )
        parametros = {"busca": busca, "filtro": filtro, "categoria": categoria}
        if so_com_preco:
            parametros["com_preco"] = "1"
        parametros = {k: v for k, v in parametros.items() if v and not (k == "filtro" and v == "todos")}
        mensagem = f"{alterados} produto(s) {'ativado' if ativar else 'desativado'}(s)."
        destino = "/catalogo?" + urlencode({**parametros, "pagina": 1, "msg": mensagem})
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/produto/{produto_id}/ativo", response_class=HTMLResponse)
    def alternar_ativo_produto(request: Request, produto_id: int):
        with sessoes() as s, s.begin():
            resultado = alternar_ativo(s, produto_id)
            if resultado is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            produto, atual = resultado
            return templates.TemplateResponse(request, "_linha_produto.html", {"p": produto, "atual": atual})

    @app.get("/produto/{produto_id}", response_class=HTMLResponse)
    def produto(request: Request, produto_id: int):
        with sessoes() as s, s.begin():
            resultado = consultas.detalhe_produto(s, produto_id)
            if resultado is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            p, atual, historico_resumo, historico_listagem = resultado
            return templates.TemplateResponse(
                request,
                "produto.html",
                {
                    "p": p,
                    "atual": atual,
                    "historico_resumo": historico_resumo,
                    "historico_listagem": historico_listagem,
                    "amazon": consultas_amazon.amazon_do_produto(s, produto_id, repo_amz.obter_config(s)),
                    "historico_amazon": consultas_amazon.historico_amazon(s, produto_id),
                },
            )

    @app.get("/ofertas", response_class=HTMLResponse)
    def ofertas(
        request: Request,
        busca: str = "",
        categoria: str = "",
        desconto_min: str = "",
        vendedor: str = "todos",
        situacao: str = "todas",
        ordem: str = "desconto",
        pagina: str = "1",
    ):
        if (
            vendedor not in consultas_amazon.VENDEDORES_OFERTAS
            or situacao not in consultas_amazon.SITUACOES_OFERTAS
            or ordem not in consultas_amazon.ORDENS_OFERTAS
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "filtro inválido")
        texto_desconto = desconto_min.strip()
        if texto_desconto and not (texto_desconto.isdecimal() and len(texto_desconto) <= 3 and int(texto_desconto) <= 100):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"desconto inválido: {desconto_min}")
        with sessoes() as s, s.begin():
            categorias = consultas.listar_categorias(s)
            if categoria and categoria not in categorias:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            cfg = repo_amz.obter_config(s)
            filtro = consultas_amazon.FiltroOfertas(
                busca=busca,
                categoria=categoria or None,
                desconto_min=int(texto_desconto) if texto_desconto else None,
                vendedor=vendedor,
                situacao=situacao,
                ordem=ordem,
            )
            linhas = consultas_amazon.ofertas(s, filtro, cfg)
            linhas_pagina, numero, paginas = historico.paginar(
                linhas, numero_pagina(pagina), consultas_amazon.POR_PAGINA_OFERTAS
            )
            parametros = {
                "busca": busca,
                "categoria": categoria,
                "desconto_min": texto_desconto,
                "vendedor": vendedor if vendedor != "todos" else "",
                "situacao": situacao if situacao != "todas" else "",
                "ordem": ordem if ordem != "desconto" else "",
            }
            parametros = {k: v for k, v in parametros.items() if v}

            def link(destino: int) -> str:
                return "/ofertas?" + urlencode({**parametros, "pagina": destino})

            return templates.TemplateResponse(
                request,
                "ofertas.html",
                {
                    "linhas": linhas_pagina,
                    "total": len(linhas),
                    "pagina": numero,
                    "paginas": paginas,
                    "link": link,
                    "f": filtro,
                    "desconto_texto": texto_desconto,
                    "categorias": categorias,
                    "vendedores": consultas_amazon.VENDEDORES_OFERTAS,
                    "ordens": consultas_amazon.ORDENS_OFERTAS,
                    "desconto_min_pct": cfg.desconto_min_pct,
                },
            )

    @app.get("/casamentos", response_class=HTMLResponse)
    def casamentos(
        request: Request,
        busca: str = "",
        categoria: str = "",
        situacao: str = "pendentes",
        com_preco: str = "",
        pagina: str = "1",
        situacao_produto: str = "",
    ):
        if situacao not in SITUACOES_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
        if situacao_produto and situacao_produto not in SITUACOES_PRODUTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação do produto inválida: {situacao_produto}")
        so_com_preco = com_preco == "1"
        with sessoes() as s, s.begin():
            categorias = consultas.listar_categorias(s)
            if categoria and categoria not in categorias:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            cfg = repo_amz.obter_config(s)
            linhas = consultas_amazon.produtos_para_casar(
                s,
                busca=busca,
                categoria=categoria or None,
                situacao=situacao,
                com_preco=so_com_preco,
                desconto_min_pct=cfg.desconto_min_pct,
                situacao_produto=situacao_produto or None,
            )
            linhas_pagina, numero, paginas = historico.paginar(
                linhas, numero_pagina(pagina), consultas_amazon.POR_PAGINA_CASAMENTOS
            )
            parametros = {
                "busca": busca, "categoria": categoria, "situacao": situacao, "situacao_produto": situacao_produto
            }
            if so_com_preco:
                parametros["com_preco"] = "1"
            parametros = {k: v for k, v in parametros.items() if v}

            def link(destino: int) -> str:
                return "/casamentos?" + urlencode({**parametros, "pagina": destino})

            return templates.TemplateResponse(
                request,
                "casamentos.html",
                {
                    "linhas": linhas_pagina,
                    "total": len(linhas),
                    "pagina": numero,
                    "paginas": paginas,
                    "link": link,
                    "voltar_atual": link(numero),
                    "busca": busca,
                    "categoria": categoria,
                    "categorias": categorias,
                    "situacao": situacao,
                    "situacoes": SITUACOES_CASAMENTO,
                    "situacao_produto": situacao_produto,
                    "situacoes_produto": SITUACOES_PRODUTO,
                    "com_preco": so_com_preco,
                },
            )

    def _tela_produto_casamento(
        request: Request, s: Session, produto_id: int, voltar: str, mensagem: tuple[str, str] | None, erro: str | None,
        link_digitado: str, codigo: int,
    ):
        cfg = repo_amz.obter_config(s)
        detalhe = detalhe_casamento(s, produto_id, cfg)
        if detalhe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        voltar = destino_seguro(voltar)
        return templates.TemplateResponse(
            request,
            "casamentos_produto.html",
            {
                "d": detalhe,
                "cfg_ia": repo_ia.obter_config_ia(s),
                "voltar": voltar,
                "aqui": f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": voltar}),
                "mensagem": mensagem,
                "explicacao_reavaliar": EXPLICACAO_REAVALIAR,
                "erro": erro,
                "link_digitado": link_digitado,
            },
            status_code=codigo,
        )

    @app.get("/casamentos/produto/{produto_id}", response_class=HTMLResponse)
    def casamento_produto(request: Request, produto_id: int, voltar: str = "/casamentos", msg: str = ""):
        with sessoes() as s, s.begin():
            return _tela_produto_casamento(
                request, s, produto_id, voltar, MENSAGENS_CASAMENTO.get(msg), None, "", status.HTTP_200_OK
            )

    @app.post("/casamentos/produto/{produto_id}/link", response_class=HTMLResponse)
    async def link_manual(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        texto = formulario.get("link", "")
        voltar = destino_seguro(formulario.get("voltar", "/casamentos"))
        with sessoes() as s, s.begin():
            produto = s.get(ProdutoLiga, produto_id)
            if produto is None or not produto.ativo:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            try:
                asin = extrair_asin(texto)
            except LinkInvalido as erro:
                return _tela_produto_casamento(
                    request, s, produto_id, voltar, None, str(erro), texto, status.HTTP_400_BAD_REQUEST
                )
            repo_amz.casar_link_manual(s, produto_id, asin, repo.agora_utc())
        destino = f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": voltar, "msg": "link_salvo"})
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    def _id_do_formulario(texto: str, campo: str) -> int:
        texto = texto.strip()
        if not (texto.isdecimal() and len(texto) <= 9):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{campo} inválido")
        return int(texto)

    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        """Ação sobre o par (anúncio, produto_id). A regra fica em `repositorio_casamento`. Em `trocar`, `de`
        (opcional) é o produto de onde você veio por "É de outro produto": o par dele fica ignorado `manual`."""
        formulario = await ler_formulario(request)
        acao = formulario.get("acao", "")
        if acao not in ("confirmar", "ignorar", "desfazer", "trocar"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        produto_id = _id_do_formulario(formulario.get("produto_id", ""), "produto_id")
        de = formulario.get("de", "").strip()
        de_id = _id_do_formulario(de, "de") if acao == "trocar" and de else None
        destino = destino_seguro(formulario.get("voltar", "/casamentos"))
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            if s.get(AnuncioAmazon, anuncio_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            if acao in ("confirmar", "trocar"):
                alvo = s.get(ProdutoLiga, produto_id)
                if alvo is None or not alvo.ativo:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
            elif repo_casamento.obter_par(s, anuncio_id, produto_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            origem = repo_ia.origem_da_decisao(s, anuncio_id, produto_id)
            try:
                if acao == "confirmar":
                    repo_casamento.confirmar(s, anuncio_id, produto_id, agora, origem)
                elif acao == "trocar":
                    repo_casamento.trocar(s, anuncio_id, produto_id, agora, origem)
                    if de_id is not None and de_id != produto_id:
                        # "É de outro produto": não é o produto de onde você veio (decisão sua sobre o par).
                        repo_casamento.ignorar(s, anuncio_id, de_id, agora, OrigemCasamento.MANUAL)
                elif acao == "ignorar":
                    repo_casamento.ignorar(s, anuncio_id, produto_id, agora, origem)
                else:
                    repo_casamento.desfazer(s, anuncio_id, produto_id, agora)
            except repo_casamento.JaConfirmado:
                destino = com_mensagem(destino, "ja_confirmado")
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = "", de: int | None = None):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            confirmado = repo_casamento.confirmado_do_anuncio(s, anuncio_id)
            excluir = {i for i in (de, confirmado.produto_id if confirmado else None) if i is not None}
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {
                    "anuncio": anuncio,
                    "busca": busca,
                    "de": de,
                    "confirmado_em": s.get(ProdutoLiga, confirmado.produto_id) if confirmado else None,
                    "sugestoes": sugestoes_para(s, anuncio, excluir=excluir),
                    "produtos": buscar_produtos(s, busca, excluir=excluir) if busca.strip() else [],
                },
            )

    def _produto_ativo_ou_404(s: Session, produto_id: int) -> ProdutoLiga:
        produto = s.get(ProdutoLiga, produto_id)
        if produto is None or not produto.ativo:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return produto

    def _volta_ao_produto(produto_id: int, voltar: str, chave: str) -> RedirectResponse:
        destino = f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": destino_seguro(voltar), "msg": chave})
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    def _casador_parado(s: Session, agora: datetime) -> str | None:
        return casador_parado(s, agora, config)

    @app.post("/casamentos/produto/{produto_id}/rebuscar")
    async def rebuscar_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            na_fila = repo_amz.priorizar_na_fila(s, produto_id, repo.agora_utc())
        chave = "rebuscar" if na_fila else "rebuscar_fora_da_fila"
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), chave)

    @app.post("/casamentos/produto/{produto_id}/reavaliar")
    async def reavaliar_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            marcados = repo_casamento.reavaliar_produto(s, produto_id, agora)
            if marcados:
                repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
            parado = _casador_parado(s, agora)
        if not marcados:
            chave = "reavaliar_nada"
        else:
            chave = f"reavaliar_{parado}" if parado else "reavaliar"
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), chave)

    @app.post("/casamentos/produto/{produto_id}/termos")
    async def gerar_termos_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            casado = repo_casamento.produto_casado(s, produto_id)
            pedido = not casado and repo_termos.pedir_termos(s, produto_id, agora)
            if pedido:
                repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
            parado = _casador_parado(s, agora)
        if casado:
            chave = "termos_ja_casado"
        elif not pedido:
            chave = "termos_fora_da_fila"
        else:
            chave = f"termos_{parado}" if parado else "termos_pedidos"
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), chave)

    return app
