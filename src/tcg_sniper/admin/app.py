import re
import secrets
from datetime import datetime, time
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.admin import consultas, consultas_amazon
from tcg_sniper.coletor_amazon.asin import LinkInvalido, extrair_asin
from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, ROTULOS, aplicar_config, validar_config
from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, AnuncioAmazon, ProdutoLiga, TipoColeta
from tcg_sniper.formatacao import formatar_brl

SENHA_PADRAO = "trocar-esta-senha"
MENSAGEM_LOTE = re.compile(r"\d{1,9} produto\(s\) (ativado|desativado)\(s\)\.")


MENSAGENS_SERVICOS = {
    "rodar": "Execução da LigaMagic solicitada; começa em até 1 minuto.",
    "retomar": "Coleta da LigaMagic retomada.",
    "amazon_pausar": "Busca na Amazon pausada.",
    "amazon_retomar": "Busca na Amazon retomada.",
}


MENSAGENS_CASAMENTO = {"link_salvo": "Link salvo; o anúncio será lido em alguns minutos."}


def destino_seguro(voltar: str) -> str:
    """Só volta para telas de Casamentos (nunca para fora do admin)."""
    if voltar.startswith("/casamentos") and not voltar.startswith("//") and "\\" not in voltar:
        return voltar
    return "/casamentos"


def numero_pagina(texto: str) -> int:
    """Número de página vindo da URL; texto inválido ou gigante vale 1 (nunca 500)."""
    texto = texto.strip()
    return int(texto) if texto.isdecimal() and len(texto) <= 9 else 1


def formatar_data(dt: datetime | None, zona: ZoneInfo) -> str:
    return "" if dt is None else dt.astimezone(zona).strftime("%d/%m/%Y %H:%M")


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

    app = FastAPI(title="TCG Sniper", dependencies=[Depends(autenticar)])
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["brl"] = formatar_brl
    templates.env.filters["envio"] = lambda envio, vendedor=None: {
        "amazon": "vendido pela Amazon",
        "fba": f"vendido por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}, enviado pela Amazon",
        "proprio": f"vendido e enviado por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}",
    }.get(envio.value, "—")
    templates.env.filters["data"] = lambda dt: formatar_data(dt, config.zona)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        liga_status: str = "todos",
        liga_pagina: str = "1",
        amazon_status: str = "todos",
        amazon_pagina: str = "1",
    ):
        for valor in (liga_status, amazon_status):
            if valor not in consultas.STATUS_HISTORICO:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status inválido: {valor}")
        agora = repo.agora_utc()
        tipos_amazon = (TipoColeta.AMAZON,)
        with sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            hora_local = agora.astimezone(config.zona).time()
            coletas, pagina_liga, paginas_liga = consultas.historico_coletas(
                s, TIPOS_LIGA, liga_status, numero_pagina(liga_pagina)
            )
            ciclos, pagina_amazon, paginas_amazon = consultas.historico_coletas(
                s, tipos_amazon, amazon_status, numero_pagina(amazon_pagina)
            )
            parametros = {
                "liga_status": liga_status,
                "liga_pagina": pagina_liga,
                "amazon_status": amazon_status,
                "amazon_pagina": pagina_amazon,
            }

            def link(**mudancas) -> str:
                return "/?" + urlencode({**parametros, **mudancas})

            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "estado": repo.obter_estado(s),
                    "em_andamento": consultas.coleta_em_andamento(s, TIPOS_LIGA),
                    "ultima_liga": consultas.ultima_coleta_sucesso(s, TIPOS_LIGA),
                    "coleta_hora": config.coleta_hora.strftime("%H:%M"),
                    "coleta_jitter": config.coleta_jitter_min,
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "ciclo_amazon": consultas_amazon.ciclo_atual(s),
                    "ultimo_ciclo": consultas.ultima_coleta_finalizada(s, tipos_amazon),
                    "fora_da_janela": not (cfg.janela_inicio <= hora_local < cfg.janela_fim),
                    "janela": f"{cfg.janela_inicio:%H:%M}–{cfg.janela_fim:%H:%M}",
                    "coletas": coletas,
                    "ciclos": ciclos,
                    "pagina_liga": pagina_liga,
                    "paginas_liga": paginas_liga,
                    "pagina_amazon": pagina_amazon,
                    "paginas_amazon": paginas_amazon,
                    "liga_status": liga_status,
                    "amazon_status": amazon_status,
                    "status_historico": consultas.STATUS_HISTORICO,
                    "link": link,
                },
            )

    @app.get("/servicos", response_class=HTMLResponse)
    def servicos(request: Request, msg: str = ""):
        with sessoes() as s, s.begin():
            return templates.TemplateResponse(
                request,
                "servicos.html",
                {
                    "estado": repo.obter_estado(s),
                    "em_andamento": consultas.coleta_em_andamento(s, TIPOS_LIGA),
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "ciclo_amazon": consultas_amazon.ciclo_atual(s),
                    "host": config.host_publico,
                    "mensagem": MENSAGENS_SERVICOS.get(msg),
                },
            )

    @app.post("/retomar")
    def retomar():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc())
        return RedirectResponse("/servicos?msg=retomar", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/rodar-agora")
    def rodar_agora():
        with sessoes() as s, s.begin():
            repo.solicitar_execucao(s, repo.agora_utc())
        return RedirectResponse("/servicos?msg=rodar", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/pausar")
    def pausar_amazon():
        with sessoes() as s, s.begin():
            repo.pausar(s, "pausado no admin", repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/servicos?msg=amazon_pausar", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/retomar")
    def retomar_amazon():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/servicos?msg=amazon_retomar", status_code=status.HTTP_303_SEE_OTHER)

    def _tela_configuracoes(request: Request, valores: dict[str, str], erros: dict[str, str], salvo: bool, codigo: int):
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "campos": CAMPOS,
                "rotulos": ROTULOS,
                "explicacoes": EXPLICACOES,
                "valores": valores,
                "erros": erros,
                "salvo": salvo,
            },
            status_code=codigo,
        )

    @app.get("/configuracoes", response_class=HTMLResponse)
    def configuracoes(request: Request, msg: str = ""):
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            valores = {
                campo: getattr(config, campo).strftime("%H:%M")
                if isinstance(getattr(config, campo), time)
                else str(getattr(config, campo))
                for campo in CAMPOS
            }
        return _tela_configuracoes(request, valores, {}, msg == "salvo", status.HTTP_200_OK)

    @app.post("/configuracoes", response_class=HTMLResponse)
    async def salvar_configuracoes(request: Request):
        formulario = await ler_formulario(request)
        valores, erros = validar_config(formulario)
        if erros:
            digitados = {campo: formulario.get(campo, "") for campo in CAMPOS}
            return _tela_configuracoes(request, digitados, erros, False, status.HTTP_400_BAD_REQUEST)
        with sessoes() as s, s.begin():
            aplicar_config(s, valores, repo.agora_utc())
        return RedirectResponse("/configuracoes?msg=salvo", status_code=status.HTTP_303_SEE_OTHER)

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
        if filtro not in consultas.FILTROS:
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
            linhas, total, numero, paginas = consultas.buscar_catalogo(
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
                    "link_anterior": link(numero - 1) if numero > 1 else None,
                    "link_proxima": link(numero + 1) if numero < paginas else None,
                    "busca": busca,
                    "filtro": filtro,
                    "filtros": consultas.FILTROS,
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
        if filtro not in consultas.FILTROS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        ativar = acao == "ativar"
        so_com_preco = com_preco == "1"
        with sessoes() as s, s.begin():
            if categoria and categoria not in consultas.listar_categorias(s):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            alterados = consultas.alterar_ativo_em_lote(
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
    def alternar_ativo(request: Request, produto_id: int):
        with sessoes() as s, s.begin():
            resultado = consultas.alternar_ativo(s, produto_id)
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
                    "amazon": consultas_amazon.amazon_do_produto(s, produto_id),
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
            linhas_pagina, numero, paginas = consultas.paginar(
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
    ):
        if situacao not in consultas_amazon.SITUACOES_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
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
            )
            linhas_pagina, numero, paginas = consultas.paginar(
                linhas, numero_pagina(pagina), consultas_amazon.POR_PAGINA_CASAMENTOS
            )
            parametros = {"busca": busca, "categoria": categoria, "situacao": situacao}
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
                    "situacoes": consultas_amazon.SITUACOES_CASAMENTO,
                    "com_preco": so_com_preco,
                },
            )

    def _tela_produto_casamento(
        request: Request, s: Session, produto_id: int, voltar: str, mensagem: str | None, erro: str | None,
        link_digitado: str, codigo: int,
    ):
        cfg = repo_amz.obter_config(s)
        detalhe = consultas_amazon.detalhe_casamento(s, produto_id, cfg.desconto_min_pct)
        if detalhe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        voltar = destino_seguro(voltar)
        return templates.TemplateResponse(
            request,
            "casamentos_produto.html",
            {
                "d": detalhe,
                "voltar": voltar,
                "aqui": f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": voltar}),
                "mensagem": mensagem,
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

    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        formulario = await ler_formulario(request)
        acao = formulario.get("acao", "")
        if acao not in ("confirmar", "ignorar", "desfazer"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            if s.get(AnuncioAmazon, anuncio_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            if acao == "confirmar":
                texto = formulario.get("produto_id", "").strip()
                if not (texto.isdecimal() and len(texto) <= 9):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "produto_id inválido")
                destino_produto = s.get(ProdutoLiga, int(texto))
                if destino_produto is None or not destino_produto.ativo:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
                repo_amz.confirmar_casamento(s, anuncio_id, int(texto), agora)
            elif acao == "ignorar":
                repo_amz.ignorar_anuncio(s, anuncio_id, agora)
            else:
                repo_amz.desfazer_casamento(s, anuncio_id, agora)
        destino = destino_seguro(formulario.get("voltar", "/casamentos"))
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = ""):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {
                    "anuncio": anuncio,
                    "busca": busca,
                    "sugestoes": consultas_amazon.sugestoes_para(s, anuncio),
                    "produtos": consultas_amazon.buscar_produtos(s, busca) if busca.strip() else [],
                },
            )

    return app
