"""O docker-compose.yml lido como texto (sem dependência de YAML): o serviço da busca da Amazon tem
perfil, noVNC e arranjo próprios; o monitor continua no perfil logado."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def bloco(servico: str) -> str:
    texto = COMPOSE.read_text(encoding="utf-8")
    inicio = texto.index(f"\n  {servico}:\n") + 1
    resto = texto[inicio + 1 :]
    fim = re.search(r"\n(?=  [a-z][a-z0-9-]*:\n|\S)", resto)
    return texto[inicio : inicio + 1 + fim.start()] if fim else texto[inicio:]


def test_servico_da_busca_com_perfil_novnc_e_arranjo_proprios():
    b = bloco("coletor-amazon-busca")
    for trecho in (
        'entrypoint: ["/app/docker/coletor-entrypoint.sh"]',
        'command: ["tcg-sniper", "coletor-amazon-busca"]',
        "DIR_PERFIL: /data/perfil-amazon-busca",
        "init: true",
        "hostname: coletor-amazon-busca",
        "stop_grace_period: 30s",
        "shm_size: 1gb",
        '- "${VNC_ESCUTA:-127.0.0.1}:6082:6080"',
        "condition: service_completed_successfully",
    ):
        assert trecho in b, trecho


def test_monitor_continua_no_perfil_logado_e_na_6081():
    b = bloco("coletor-amazon")
    assert "DIR_PERFIL: /data/perfil-amazon\n" in b
    assert '- "${VNC_ESCUTA:-127.0.0.1}:6081:6080"' in b and 'command: ["tcg-sniper", "coletor-amazon"]' in b


def test_portas_do_novnc_nao_se_repetem():
    assert sorted(re.findall(r'- "(?:\$\{VNC_ESCUTA:-127\.0\.0\.1\}:)?(\d+):6080"', COMPOSE.read_text(encoding="utf-8"))) == ["6080", "6081", "6082"]
