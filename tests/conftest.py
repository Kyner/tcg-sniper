import pytest

from tcg_sniper.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(
        _env_file=None,
        dir_dados=tmp_path,
        liga_url_catalogo="https://liga.test/selados",
        host_publico="host.test",
        pausa_min_s=8,
        pausa_max_s=20,
        limite_falha_pct=50,
    )
