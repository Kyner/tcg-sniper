from enum import StrEnum


class Destino(StrEnum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"
    INDIVIDUAL = "individual"  # número de uma pessoa (código de acesso); nunca um grupo
