import argparse
import logging
import signal

from tcg_sniper.config import Config
from tcg_sniper.db.session import criar_engine, criar_sessoes, migrar


def _encerrar(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def instalar_sigterm() -> None:
    """SIGTERM (docker stop) vira SystemExit: o loop do agendador desenrola e o Chromium fecha."""
    signal.signal(signal.SIGTERM, _encerrar)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tcg-sniper")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("migrate", help="aplica as migrações do banco")
    sub.add_parser("coletor-liga", help="inicia o agendador de coletas da LigaMagic")
    sub.add_parser("coletor-amazon", help="inicia a fila contínua de buscas na Amazon")
    sub.add_parser("notificador", help="envia a tabela de saída do WhatsApp pela Evolution API")
    sub.add_parser("casador", help="avalia com a IA os anúncios pendentes da Amazon")
    admin = sub.add_parser("admin", help="inicia a página de admin")
    admin.add_argument("--porta", type=int, default=8000)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()

    if args.comando == "migrate":
        migrar(config.database_url)
        return

    engine = criar_engine(config.database_url)
    sessoes = criar_sessoes(engine)

    if args.comando == "coletor-liga":
        from tcg_sniper.coletor_liga.agendador import Agendador
        from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright
        from tcg_sniper.notificador import criar_notificador

        instalar_sigterm()
        Agendador(
            engine,
            sessoes,
            lambda: NavegadorPlaywright(config.dir_dados / "perfil"),
            criar_notificador(config, sessoes),
            config,
        ).rodar()
    elif args.comando == "coletor-amazon":
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura import VarreduraAmazon
        from tcg_sniper.navegador.chromium import NavegadorChromium
        from tcg_sniper.notificador import criar_notificador

        instalar_sigterm()
        VarreduraAmazon(
            engine,
            sessoes,
            lambda: NavegadorChromium(config.dir_dados / "perfil-amazon", eh_desafio_amazon),
            criar_notificador(config, sessoes),
            config,
        ).rodar()
    elif args.comando == "notificador":
        from tcg_sniper.notificador import servico

        notificador = servico.ServicoNotificador(sessoes, config)
        # SIGTERM pede parada limpa: não corta o envio HTTP no meio (SystemExit).
        signal.signal(signal.SIGTERM, lambda _signum, _frame: notificador.parar())
        notificador.rodar()
    elif args.comando == "casador":
        from tcg_sniper.casador.servico import ServicoCasador
        from tcg_sniper.ia.transporte_openai import TransporteOpenAI
        from tcg_sniper.notificador import criar_notificador

        chave = (config.openai_api_key or "").strip()
        casador = ServicoCasador(sessoes, TransporteOpenAI(chave) if chave else None, config, criar_notificador(config, sessoes))
        signal.signal(signal.SIGTERM, lambda _signum, _frame: casador.parar())
        casador.rodar()
    elif args.comando == "admin":
        import uvicorn

        from tcg_sniper.admin.app import criar_app

        uvicorn.run(criar_app(sessoes, config), host="0.0.0.0", port=args.porta)
