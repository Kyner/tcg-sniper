import argparse
import logging
import signal
from zoneinfo import ZoneInfo

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
    ia = sub.add_parser("ia", help="ferramentas da IA")
    ia_sub = ia.add_subparsers(dest="acao_ia", required=True)
    avaliar_p = ia_sub.add_parser("avaliar", help="mede a IA nos casamentos já decididos (não muda nada)")
    avaliar_p.add_argument("--modelo", action="append", required=True, help="pode repetir para comparar modelos")
    avaliar_p.add_argument("--limite", type=int, default=None, help="no máximo N anúncios")
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
    elif args.comando == "ia":
        import httpx

        from tcg_sniper.casador.avaliacao import avaliar, relatorio_markdown
        from tcg_sniper.db import repositorio as repo
        from tcg_sniper.ia.transporte_openai import TransporteOpenAI

        chave = (config.openai_api_key or "").strip()
        if not chave:
            raise SystemExit("OPENAI_API_KEY ausente no .env")
        with sessoes() as s:
            zona = ZoneInfo(repo.obter_config_geral(s, config).fuso)
        agora = repo.agora_utc()
        with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as http:
            resultados = avaliar(sessoes, TransporteOpenAI(chave), http, args.modelo, args.limite, zona, repo.agora_utc)
        destino = config.dir_dados / f"avaliacao-ia-{agora:%Y-%m-%d-%H%M}.md"
        destino.write_text(relatorio_markdown(resultados, agora), encoding="utf-8")
        print(f"relatório em {destino}")
    elif args.comando == "admin":
        import uvicorn

        from tcg_sniper.admin.app import criar_app

        uvicorn.run(criar_app(sessoes, config), host="0.0.0.0", port=args.porta)
