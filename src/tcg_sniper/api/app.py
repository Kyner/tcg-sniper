"""App FastAPI do serviço `api` (`tcg-sniper api`). Só rotas /api em JSON; sem CORS (o front vem da mesma origem,
pelo Caddy). A documentação OpenAPI fica em /api/docs e exige `ver_documentacao_api`. Não sobe sem `SEGREDO_API`."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.api import (
    rotas_acessos,
    rotas_auth,
    rotas_gestao_atividade,
    rotas_gestao_casamentos,
    rotas_gestao_catalogo,
    rotas_gestao_configuracoes,
    rotas_gestao_dashboard,
    rotas_gestao_servicos,
    rotas_oportunidades,
    rotas_usuarios,
)
from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi, instalar_tratadores
from tcg_sniper.api.permissoes import GradePermissoes, Permissao
from tcg_sniper.api.segredos import exigir_segredo
from tcg_sniper.config import Config
from tcg_sniper.db.repositorio import agora_utc

log = logging.getLogger(__name__)


def criar_app(
    sessoes: sessionmaker[Session], config: Config, relogio: Callable[[], datetime] | None = None
) -> FastAPI:
    segredo = exigir_segredo(config)  # sem SEGREDO_API válida a API não sobe (SegredoAusente)
    app = FastAPI(title="TCG Sniper · API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.segredo = segredo
    app.state.sessoes = sessoes
    app.state.config = config
    app.state.relogio = relogio or agora_utc
    app.state.grade = GradePermissoes(sessoes)
    instalar_tratadores(app)
    app.include_router(rotas_acessos.roteador)
    app.include_router(rotas_usuarios.roteador)
    app.include_router(rotas_auth.roteador)
    app.include_router(rotas_oportunidades.roteador)
    app.include_router(rotas_gestao_atividade.roteador)
    app.include_router(rotas_gestao_casamentos.roteador)
    app.include_router(rotas_gestao_catalogo.roteador)
    app.include_router(rotas_gestao_configuracoes.roteador)
    app.include_router(rotas_gestao_dashboard.roteador)
    app.include_router(rotas_gestao_servicos.roteador)

    VerDocumentacao = Annotated[Contexto, Depends(exige(Permissao.VER_DOCUMENTACAO_API))]

    @app.get("/api/saude")
    def saude() -> dict[str, bool]:
        """Sem login: o banco responde?"""
        try:
            with sessoes() as s:
                s.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - qualquer falha do banco vira 503 (o erro não vai para a resposta)
            log.warning("saúde: o banco não respondeu")
            raise ErroApi(503, "banco_fora", "O banco de dados não respondeu.") from None
        return {"ok": True}

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi(_contexto: VerDocumentacao) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/api/docs", include_in_schema=False)
    def docs(_contexto: VerDocumentacao) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="TCG Sniper · API")

    return app
