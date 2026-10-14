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
from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, ROTULOS, aplicar_config, validar_config
from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, AnuncioAmazon, ProdutoLiga, TipoColeta
from tcg_sniper.formatacao import formatar_brl

SENHA_PADRAO = "trocar-esta-senha"
MENSAGEM_LOTE = re.compile(r"\d{1,9} produto\(s\) (ativado|desativado)\(s\)\.")


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
    def index(request: Request):
        with sessoes() as s, s.begin():
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "estado": repo.obter_estado(s),
                    "coletas": consultas.listar_coletas(s, TIPOS_LIGA),
                    "ciclos_amazon": consultas.listar_coletas(s, (TipoColeta.AMAZON,)),
                    "em_andamento": consultas.coleta_em_andamento(s, TIPOS_LIGA),
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "ciclo_amazon": consultas_amazon.ciclo_atual(s),
                    "host": config.host_publico,
                },
            )

    @app.post("/retomar")
    def retomar():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc())
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/rodar-agora")
    def rodar_agora():
        with sessoes() as s, s.begin():
            repo.solicitar_execucao(s, repo.agora_utc())
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/pausar")
    def pausar_amazon():
        with sessoes() as s, s.begin():
            repo.pausar(s, "pausado no admin", repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/retomar")
    def retomar_amazon():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

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
    def ofertas(request: Request, filtro: str = "todas"):
        if filtro not in consultas_amazon.FILTROS_OFERTAS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            return templates.TemplateResponse(
                request,
                "ofertas.html",
                {
                    "linhas": consultas_amazon.ofertas(s, filtro, config),
                    "filtro": filtro,
                    "filtros": consultas_amazon.FILTROS_OFERTAS,
                    "desconto_min_pct": config.desconto_min_pct,
                },
            )

    ABAS_CASAMENTO = ("pendentes", "revisados")

    @app.get("/casamentos", response_class=HTMLResponse)
    def casamentos(request: Request, aba: str = "pendentes"):
        if aba not in ABAS_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"aba inválida: {aba}")
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            if aba == "pendentes":
                linhas, total = consultas_amazon.pendentes(s, config.desconto_min_pct)
            else:
                linhas, total = [], consultas_amazon.contar_pendentes(s)
            return templates.TemplateResponse(
                request,
                "casamentos.html",
                {
                    "aba": aba,
                    "linhas": linhas,
                    "total": total,
                    "revisados": consultas_amazon.revisados(s) if aba == "revisados" else [],
                    "desconto_min_pct": config.desconto_min_pct,
                },
            )

    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        formulario = await ler_formulario(request)
        acao, aba = formulario.get("acao", ""), formulario.get("aba", "pendentes")
        if acao not in ("confirmar", "ignorar", "desfazer") or aba not in ABAS_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            if s.get(AnuncioAmazon, anuncio_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            if acao == "confirmar":
                texto = formulario.get("produto_id", "").strip()
                if not (texto.isdecimal() and len(texto) <= 9):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "produto_id inválido")
                if s.get(ProdutoLiga, int(texto)) is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
                repo_amz.confirmar_casamento(s, anuncio_id, int(texto), agora)
            elif acao == "ignorar":
                repo_amz.ignorar_anuncio(s, anuncio_id, agora)
            else:
                repo_amz.desfazer_casamento(s, anuncio_id, agora)
        return RedirectResponse(f"/casamentos?aba={aba}", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = ""):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {"anuncio": anuncio, "busca": busca, "produtos": consultas_amazon.buscar_produtos(s, busca)},
            )

    return app
