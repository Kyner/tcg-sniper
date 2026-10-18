from tcg_sniper.manutencao import r2

SEGREDO = "segredo-falso-r2-0123456789"


def _config(config, **mudancas):
    valores = {
        "r2_account_id": "conta123", "r2_access_key_id": "ID-FALSO-R2", "r2_secret_access_key": SEGREDO,
        "r2_bucket": "balde", **mudancas,
    }
    return config.model_validate({**config.model_dump(), **valores})


class ClienteFake:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.enviados = []

    def upload_file(self, caminho, bucket, chave):
        self.enviados.append((caminho, bucket, chave))


def test_sem_as_quatro_variaveis_nao_ha_enviador(config):
    assert r2.criar_enviador(config) is None
    assert r2.criar_enviador(_config(config, r2_bucket="")) is None


def test_enviador_usa_o_endpoint_da_conta_e_a_regiao_auto(config, tmp_path):
    criados = []

    def fabrica(**kwargs):
        criados.append(ClienteFake(**kwargs))
        return criados[-1]

    enviador = r2.EnviadorR2(_config(config), fabrica)
    arquivo = tmp_path / "tcg-diario-2026-10-18.dump"
    enviador.enviar(arquivo, "diario/tcg-2026-10-18.dump")

    cliente = criados[0]
    assert cliente.kwargs["endpoint_url"] == "https://conta123.r2.cloudflarestorage.com"
    assert cliente.kwargs["region_name"] == "auto"
    assert cliente.kwargs["aws_secret_access_key"] == SEGREDO
    assert cliente.enviados == [(str(arquivo), "balde", "diario/tcg-2026-10-18.dump")]
    assert SEGREDO not in repr(enviador) and SEGREDO in enviador.segredos


def test_cliente_boto3_de_verdade_e_criado_sem_rede(config):
    enviador = r2.criar_enviador(_config(config))
    assert enviador is not None
    assert enviador._cliente.meta.endpoint_url == "https://conta123.r2.cloudflarestorage.com"
    assert enviador._cliente.meta.region_name == "auto"
