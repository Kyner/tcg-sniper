from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db.models import (
    PADROES_CONFIG_AMAZON,
    Base,
    ConfigAmazon,
    EstadoColetor,
    EstadoColetorTipo,
    VendedorAmazon,
)


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
