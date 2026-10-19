import fakes_api
import pytest
from fastapi.testclient import TestClient

from tcg_sniper.api.app import criar_app


@pytest.fixture
def relogio():
    return fakes_api.Relogio()


@pytest.fixture
def app_api(sessoes, config, relogio):
    """Um app por teste: o cache da grade de permissões não passa de um teste para outro."""
    return criar_app(sessoes, config, relogio=relogio)


@pytest.fixture
def cliente(app_api):
    return TestClient(app_api)


@pytest.fixture
def logar(sessoes, cliente):
    def _logar(papel, **kwargs):
        return fakes_api.logar(sessoes, cliente, papel, **kwargs)

    return _logar
