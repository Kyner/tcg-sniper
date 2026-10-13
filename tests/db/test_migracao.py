from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db.models import Base, EstadoColetor, EstadoColetorTipo


def test_migracao_igual_aos_modelos(engine):
    with engine.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_estado_coletor_aceita_so_uma_linha(s):
    agora = datetime.now(UTC)
    s.add(EstadoColetor(id=2, estado=EstadoColetorTipo.ATIVO, atualizado_em=agora))
    with pytest.raises(IntegrityError):
        s.flush()
