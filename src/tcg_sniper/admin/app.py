import secrets
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.admin import consultas
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo


def formatar_brl(valor: Decimal | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def formatar_data(dt: datetime | None, zona: ZoneInfo) -> str:
    return "" if dt is None else dt.astimezone(zona).strftime("%d/%m/%Y %H:%M")


def criar_app(sessoes: sessionmaker[Session], config: Config) -> FastAPI:
    seguranca = HTTPBasic()

    def autenticar(credenciais: Annotated[HTTPBasicCredentials, Depends(seguranca)]) -> None:
        if not secrets.compare_digest(credenciais.password.encode(), config.admin_senha.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    app = FastAPI(title="TCG Sniper", dependencies=[Depends(autenticar)])
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["brl"] = formatar_brl
    templates.env.filters["data"] = lambda dt: formatar_data(dt, config.zona)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with sessoes() as s, s.begin():
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "estado": repo.obter_estado(s),
                    "coletas": consultas.listar_coletas(s),
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

    @app.get("/catalogo", response_class=HTMLResponse)
    def catalogo(request: Request, busca: str = "", filtro: str = "todos"):
        if filtro not in consultas.FILTROS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        with sessoes() as s, s.begin():
            linhas = consultas.buscar_catalogo(s, busca, filtro, repo.agora_utc())
            return templates.TemplateResponse(
                request,
                "catalogo.html",
                {"linhas": linhas, "busca": busca, "filtro": filtro, "filtros": consultas.FILTROS},
            )

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
            p, atual, historico = resultado
            return templates.TemplateResponse(
                request, "produto.html", {"p": p, "atual": atual, "historico": historico}
            )

    return app
