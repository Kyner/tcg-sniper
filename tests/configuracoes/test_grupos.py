from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from tcg_sniper.coletor_amazon.config import CAMPOS, aplicar_config
from tcg_sniper.config import Config
from tcg_sniper.configuracoes.geral_liga import CAMPOS_GERAL, CAMPOS_LIGA
from tcg_sniper.configuracoes.grupos import GRUPOS, campo, valores_atuais, versoes
from tcg_sniper.configuracoes.ia import CAMPOS_IA
from tcg_sniper.gestao import servicos

IDS = (
    "oportunidades", "vendedores", "busca", "monitor", "checkout", "bloqueio", "liga",
    "ia-decide", "ia-ritmo", "ia-gasto", "ia-modelo", "whatsapp", "sistema",
)
SERVICOS = ("amazon.monitor_ligado", "amazon.checkout_ligado", "amazon.checkout_sem_login_em")


def _chaves() -> list[str]:
    return [c.chave for g in GRUPOS for c in g.campos]


def test_grupos_na_ordem_da_spec():
    assert tuple(g.id for g in GRUPOS) == IDS
    com_efeito = {g.id for g in GRUPOS if g.tem_efeito}
    assert com_efeito == {"oportunidades", "busca", "monitor", "checkout", "bloqueio", "ia-decide", "ia-ritmo", "ia-gasto"}
    assert all(g.titulo and g.proposito for g in GRUPOS)


def test_grupos_cobrem_todos_os_campos_editaveis():
    chaves = _chaves()
    esperadas = (
        [f"amazon.{c}" for c in CAMPOS] + [f"geral.{c}" for c in CAMPOS_GERAL]
        + [f"liga.{c}" for c in CAMPOS_LIGA] + [f"ia.{c}" for c in CAMPOS_IA]
    )
    assert len(chaves) == len(set(chaves))  # cada campo uma vez
    assert sorted(chaves) == sorted(esperadas)
    assert not set(SERVICOS) & set(chaves)


def test_encaixes_da_decisao_5():
    por_grupo = {g.id: [c.chave for c in g.campos] for g in GRUPOS}
    assert "geral.validade_oportunidade_h" in por_grupo["oportunidades"]
    assert "amazon.monitor_esgotado_dias" in por_grupo["monitor"]
    assert campo("amazon.monitor_esgotado_dias").avancado
    assert por_grupo["bloqueio"] == ["amazon.pausa_min_s", "amazon.pausa_max_s"]
    assert {"liga.pausa_min_s", "liga.pausa_max_s"} <= set(por_grupo["liga"])
    assert all(c.avancado for c in next(g for g in GRUPOS if g.id == "ia-modelo").campos)
    assert [c.chave for c in next(g for g in GRUPOS if g.id == "busca").campos if c.avancado] == [
        "amazon.url_busca", "amazon.resultados_por_busca", "amazon.limite_falha_pct",
    ]


def test_metadados_dos_campos():
    desconto = campo("amazon.desconto_min_pct")
    assert (desconto.tipo, desconto.padrao, desconto.minimo, desconto.maximo) == ("int", 25, Decimal(1), Decimal(90))
    assert desconto.rotulo and desconto.explicacao
    assert campo("amazon.quase_oportunidade_min_pct").vinculo == "menor que o desconto mínimo"
    assert campo("amazon.janela_inicio").tipo == "hora"
    assert campo("amazon.janela_inicio").padrao == time(8, 0)
    pausa_liga = campo("liga.pausa_max_s")
    assert (pausa_liga.tipo, pausa_liga.padrao, pausa_liga.maximo) == ("float", 20.0, Decimal(120))
    assert campo("liga.categorias").tipo == "categorias"
    assert campo("ia.teto_dia_usd").tipo == "decimal"
    assert campo("ia.teto_dia_usd").padrao == Decimal("2.00")
    assert campo("ia.ligado").tipo == "bool"
    assert campo("geral.validade_oportunidade_h").padrao == 6


def test_esforco_em_portugues():
    esforco = campo("ia.esforco")
    assert esforco.tipo == "escolha"
    assert esforco.opcoes == (("minimal", "mínimo"), ("low", "baixo"), ("medium", "médio"), ("high", "alto"))


def test_valores_atuais_das_quatro_tabelas(s, config):
    valores = valores_atuais(s, config)
    assert set(valores) == set(_chaves())
    assert valores["amazon.desconto_min_pct"] == 25
    assert valores["geral.host_publico"] == "host.test"
    assert valores["liga.categorias"] == "10,11,12"
    assert valores["ia.esforco"] == "low"


def test_valores_sem_segredo(s, tmp_path):
    segredos = {
        "admin_senha": "senha-secreta-xyz", "openai_api_key": "sk-secreta-xyz", "evolution_api_key": "evo-secreta-xyz",
        "evolution_url": "http://evolution.secreta.xyz", "segredo_api": "segredo-secreto-xyz-0123456789abcdefghij",
        "r2_account_id": "conta-secreta-xyz", "r2_access_key_id": "chave-secreta-xyz",
        "r2_secret_access_key": "r2-secreta-xyz", "database_url": "postgresql+psycopg://x:secreta@h:1/xyz",
    }
    config = Config(_env_file=None, dir_dados=tmp_path, **segredos)
    valores = valores_atuais(s, config)
    texto = repr(valores)
    assert not any(v in texto for v in segredos.values())
    assert not {k.split(".", 1)[1] for k in valores} & set(segredos)
    assert not set(SERVICOS) & set(valores)


def test_versoes_por_tabela(s, config):
    valores_atuais(s, config)
    v = versoes(s)
    assert set(v) == {"geral", "liga", "amazon", "ia"}
    assert all(isinstance(x, str) and "T" in x for x in v.values())


def test_ligar_e_desligar_servicos_nao_mudam_a_versao_das_configuracoes(s, config):
    valores_atuais(s, config)
    antes = versoes(s)["amazon"]
    depois = datetime.now(UTC) + timedelta(hours=1)
    servicos.ajustar_amazon(s, "monitor_ligado", True, depois)
    servicos.ajustar_amazon(s, "checkout_ligado", True, depois)
    servicos.retomar_checkout(s, depois)
    aplicar_config(s, {"checkout_sem_login_em": depois}, depois)
    assert versoes(s)["amazon"] == antes


def test_salvar_campo_de_configuracao_muda_a_versao(s, config):
    valores_atuais(s, config)
    antes = versoes(s)["amazon"]
    aplicar_config(s, {"desconto_min_pct": 30}, datetime.now(UTC) + timedelta(hours=1))
    assert versoes(s)["amazon"] != antes
