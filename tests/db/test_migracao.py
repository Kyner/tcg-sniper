from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, pool, select, text, update
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db.models import (
    PADROES_CONFIG_AMAZON,
    Base,
    ConfigAmazon,
    ConfigGeral,
    ConfigLiga,
    EstadoColetor,
    EstadoColetorTipo,
    VendedorAmazon,
)
from tcg_sniper.db.session import config_alembic


def test_migracao_igual_aos_modelos(engine):
    with engine.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_estado_coletor_aceita_so_as_linhas_dos_coletores(s):
    agora = datetime.now(UTC)
    s.add(EstadoColetor(id=3, coletor="outro", estado=EstadoColetorTipo.ATIVO, atualizado_em=agora))
    with pytest.raises(IntegrityError):
        s.flush()


def test_insert_do_codigo_antigo_sem_coletor_nao_quebra(s):
    """O `obter_estado` antigo (antes da Amazon) insere a linha 1 sem `coletor`: tem que conflitar em paz."""
    s.execute(
        text(
            "INSERT INTO estado_coletor (id, estado, execucao_solicitada, atualizado_em) "
            "VALUES (1, 'ativo', false, now()) ON CONFLICT (id) DO NOTHING"
        )
    )
    assert s.get(EstadoColetor, 1).coletor == "liga"


def test_migracao_cria_estado_da_amazon_ativo(s):
    estado = s.get(EstadoColetor, 2)
    assert (estado.coletor, estado.estado) == ("amazon", EstadoColetorTipo.ATIVO)


def test_migracao_cria_config_amazon_com_os_padroes(s):
    config = s.get(ConfigAmazon, 1)
    for campo, valor in PADROES_CONFIG_AMAZON.items():
        assert getattr(config, campo) == valor, campo


def test_migracao_cria_o_vendedor_amazon(s):
    vendedor = s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == "amazon"))
    assert vendedor.nome == "Amazon.com.br"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("resultados_por_busca", 0),
        ("resultados_por_busca", 49),
        ("max_buscas_hora", 401),
        ("desconto_min_pct", 0),
        ("intervalo_busca_min", 9),
        ("pausa_max_s", 121),
        ("url_busca", "https://www.amazon.com.br/s?k=x"),
    ],
)
def test_config_amazon_recusa_valores_fora_dos_limites(s, campo, valor):
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values({campo: valor}))


def test_config_amazon_recusa_pausa_minima_maior_que_a_maxima(s):
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values(pausa_min_s=30, pausa_max_s=20))


def test_migracao_amazon_preserva_os_dados_da_liga(engine):
    """Fora da transação do `sessoes`: desce o banco de testes para o schema inicial, grava dados da Liga,
    sobe de novo e confere. Sempre deixa o banco em head para os outros testes."""
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    with proprio.connect() as conexao:
        linha_liga_antes = conexao.execute(text("SELECT * FROM estado_coletor WHERE id = 1")).first()
    coleta_id = None
    try:
        command.downgrade(cfg, "5c815103a38f")
        with proprio.begin() as conexao:
            conexao.execute(text("DELETE FROM estado_coletor"))
            conexao.execute(
                text(
                    "INSERT INTO estado_coletor (id, estado, motivo, execucao_solicitada, atualizado_em) "
                    "VALUES (1, 'pausado_desafio', 'desafio em x', false, now())"
                )
            )
            coleta_id = conexao.scalar(
                text(
                    "INSERT INTO coleta (tipo, iniciada_em, status, produtos_ok, produtos_falha) "
                    "VALUES ('produtos', now(), 'ok', 7, 1) RETURNING id"
                )
            )
        command.upgrade(cfg, "head")
        with proprio.connect() as conexao:
            estados = conexao.execute(
                text("SELECT id, coletor, estado, motivo FROM estado_coletor ORDER BY id")
            ).all()
            coleta = conexao.execute(
                text("SELECT tipo, status, produtos_ok, produtos_falha FROM coleta WHERE id = :id"), {"id": coleta_id}
            ).one()
            configs = conexao.scalar(text("SELECT count(*) FROM config_amazon WHERE id = 1"))
        assert [tuple(e) for e in estados] == [
            (1, "liga", "pausado_desafio", "desafio em x"),
            (2, "amazon", "ativo", None),
        ]
        assert tuple(coleta) == ("produtos", "ok", 7, 1)
        assert configs == 1
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as conexao:  # devolve o banco como estava
            conexao.execute(text("DELETE FROM coleta WHERE id = :id"), {"id": coleta_id})
            if linha_liga_antes is None:
                conexao.execute(text("DELETE FROM estado_coletor WHERE id = 1"))
            else:
                conexao.execute(
                    text("UPDATE estado_coletor SET estado = :estado, motivo = :motivo WHERE id = 1"),
                    {"estado": linha_liga_antes.estado, "motivo": linha_liga_antes.motivo},
                )
        proprio.dispose()


def test_migracao_cria_config_geral_e_liga_vazias(s):
    assert s.get(ConfigGeral, 1) is None
    assert s.get(ConfigLiga, 1) is None
