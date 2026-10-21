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


def test_segredos_sem_espacos_e_com_o_account_id(config):
    enviador = r2.EnviadorR2(
        _config(config, r2_account_id=" conta-abc123 ", r2_secret_access_key=f"  {SEGREDO}\n"), ClienteFake
    )
    assert set(enviador.segredos) == {SEGREDO, "ID-FALSO-R2", "conta-abc123"}


def test_imagens_usam_o_bucket_de_imagens_e_nunca_o_dos_backups(config):
    cfg = _config(config, r2_bucket_imagens="balde-imagens")
    criados = []

    def fabrica(**kwargs):
        criados.append(ClienteImagens(**kwargs))
        return criados[-1]

    enviador = r2.EnviadorR2(
        cfg, fabrica, bucket=cfg.r2_bucket_imagens, chaves=cfg.chaves_r2_imagens()
    )
    enviador.enviar_bytes(b"x", "produtos/p1-abc.webp", "image/webp", "public, immutable")
    (put,) = criados[0].puts
    assert put["Bucket"] == "balde-imagens" and put["Bucket"] != cfg.r2_bucket
    assert put["ContentType"] == "image/webp" and put["CacheControl"] == "public, immutable"
    assert put["Key"] == "produtos/p1-abc.webp" and put["Body"] == b"x"


def test_criar_enviador_imagens_nunca_cai_no_bucket_dos_backups(config):
    assert r2.criar_enviador_imagens(_config(config)) is None  # só o bucket dos backups: nada de imagens
    enviador = r2.criar_enviador_imagens(_config(config, r2_bucket_imagens=" balde-imagens "))
    assert enviador is not None
    assert enviador._bucket == "balde-imagens" and enviador._bucket != "balde"


class ClienteImagens(ClienteFake):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
