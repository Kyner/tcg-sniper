"""Portas publicadas no docker-compose.yml: nada aberto para a rede de casa sem o usuário pedir.

O admin antigo e o noVNC (o navegador logado na Amazon) escutam só neste PC por padrão; `ADMIN_ESCUTA` e
`VNC_ESCUTA` no `.env` reabrem. O arquivo é lido como texto (sem depender de um leitor de YAML)."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
PORTA = re.compile(r'^\s+- "([^"]*\d+:\d+)"\s*$')  # "porta:porta" (aberta) ou "endereço:porta:porta"


def _portas_por_servico() -> dict[str, list[str]]:
    portas: dict[str, list[str]] = {}
    servico = None
    for linha in COMPOSE.read_text(encoding="utf-8").splitlines():
        nome = re.match(r"^  ([a-z][a-z0-9-]*):\s*$", linha)
        if nome:
            servico = nome.group(1)
            continue
        porta = PORTA.match(linha)
        if porta and servico:
            portas.setdefault(servico, []).append(porta.group(1))
    return portas


def test_admin_e_novnc_escutam_so_neste_pc_por_padrao():
    portas = _portas_por_servico()
    assert portas["admin"] == ["${ADMIN_ESCUTA:-127.0.0.1}:8000:8000"]
    assert portas["coletor-liga"] == ["${VNC_ESCUTA:-127.0.0.1}:6080:6080"]
    assert portas["coletor-amazon"] == ["${VNC_ESCUTA:-127.0.0.1}:6081:6080"]
    assert portas["coletor-amazon-busca"] == ["${VNC_ESCUTA:-127.0.0.1}:6082:6080"]


def test_nenhuma_porta_publicada_aberta_sem_variavel():
    portas = [p for lista in _portas_por_servico().values() for p in lista]
    assert portas, "nenhuma porta encontrada: o formato do compose mudou?"
    abertas = [p for p in portas if not re.match(r"^(127\.0\.0\.1|\$\{[A-Z_]+:-127\.0\.0\.1\}):", p)]
    assert abertas == []
