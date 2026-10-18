import argparse
import logging
import signal
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.vigia import Batimento
from tcg_sniper.config import Config
from tcg_sniper.db.session import criar_engine, criar_sessoes, migrar


def _encerrar(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def instalar_sigterm() -> None:
    """SIGTERM (docker stop) vira SystemExit: o loop do agendador desenrola e o Chromium fecha."""
    signal.signal(signal.SIGTERM, _encerrar)


def _preco(texto: str) -> Decimal:
    """Preço em US$ por milhão de tokens; aceita vírgula decimal."""
    try:
        valor = Decimal(texto.strip().replace(",", "."))
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"preço inválido: {texto}") from None
    if not valor.is_finite() or valor < 0:
        raise argparse.ArgumentTypeError(f"preço inválido: {texto}")
    return valor


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tcg-sniper")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("migrate", help="aplica as migrações do banco")
    sub.add_parser("coletor-liga", help="inicia o agendador de coletas da LigaMagic")
    sub.add_parser("coletor-amazon", help="inicia a fila contínua de buscas na Amazon")
    sub.add_parser("notificador", help="envia a tabela de saída do WhatsApp pela Evolution API")
    sub.add_parser("casador", help="avalia com a IA os anúncios pendentes da Amazon")
    sub.add_parser("manutencao", help="backup diário do banco (com cópia no R2) e limpeza do histórico antigo")
    ia = sub.add_parser("ia", help="ferramentas da IA")
    ia_sub = ia.add_subparsers(dest="acao_ia", required=True)
    avaliar_p = ia_sub.add_parser("avaliar", help="mede a IA nos casamentos já decididos (não muda nada)")
    avaliar_p.add_argument("--modelo", action="append", required=True, help="pode repetir para comparar modelos")
    avaliar_p.add_argument("--limite", type=int, default=None, help="no máximo N anúncios")
    avaliar_p.add_argument("--preco-entrada", type=_preco, default=None, help="US$ por milhão de tokens de entrada (padrão: o de Configurações, aba IA)")
    avaliar_p.add_argument("--preco-saida", type=_preco, default=None, help="US$ por milhão de tokens de saída (padrão: o de Configurações, aba IA)")
    amazon = sub.add_parser("amazon", help="ferramentas da Amazon")
    amazon_sub = amazon.add_subparsers(dest="acao_amazon", required=True)
    capturar_p = amazon_sub.add_parser(
        "capturar", help="salva páginas reais para as fixtures (pare o coletor-amazon antes)"
    )
    capturar_p.add_argument("--asin", action="append", required=True, type=str.upper, help="pode repetir")
    capturar_p.add_argument(
        "--checkout", action="store_true",
        help="também põe a oferta em destaque do 1º ASIN no carrinho, vai ao resumo do pedido (sem confirmar) e tira o item",
    )
    capturar_p.add_argument("--login", action="store_true", help="também salva a página de login (perfil temporário)")
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

        Batimento(sessoes, "liga").iniciar()
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

        Batimento(sessoes, "amazon").iniciar()
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
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.casador.servico import ServicoCasador
        from tcg_sniper.ia.transporte_openai import TransporteOpenAI

        chave = (config.openai_api_key or "").strip()
        # timeout e repetições menores que os do padrão: o desligamento (stop_grace_period) espera a chamada em curso
        transporte = TransporteOpenAI(chave, timeout_s=30, max_retries=2) if chave else None
        casador = ServicoCasador(sessoes, transporte, config, criar_avisador(sessoes))
        signal.signal(signal.SIGTERM, lambda _signum, _frame: casador.parar())
        Batimento(sessoes, "casador").iniciar()
        casador.rodar()
    elif args.comando == "manutencao":
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.manutencao.r2 import criar_enviador
        from tcg_sniper.manutencao.servico import ServicoManutencao

        manutencao = ServicoManutencao(sessoes, config, criar_avisador(sessoes), criar_enviador(config))
        # SIGTERM pede parada limpa: o backup em andamento termina (stop_grace_period no compose).
        signal.signal(signal.SIGTERM, lambda _signum, _frame: manutencao.parar())
        manutencao.rodar()
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
            resultados = avaliar(
                sessoes, TransporteOpenAI(chave), http, args.modelo, args.limite, zona, repo.agora_utc,
                preco_entrada=args.preco_entrada, preco_saida=args.preco_saida,
            )
        destino = config.dir_dados / f"avaliacao-ia-{agora:%Y-%m-%d-%H%M}.md"
        relatorio = relatorio_markdown(resultados, agora, preco_entrada=args.preco_entrada, preco_saida=args.preco_saida)
        destino.write_text(relatorio, encoding="utf-8")
        print(f"relatório em {destino}")
    elif args.comando == "amazon":
        import random
        import tempfile
        import time
        from pathlib import Path

        from tcg_sniper.coletor_amazon.captura import Captura, capturar, capturar_login
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura import ID_LOCK_AMAZON
        from tcg_sniper.coletor_liga import agendador
        from tcg_sniper.db import repositorio as repo
        from tcg_sniper.navegador.chromium import NavegadorChromium

        destino = config.dir_dados / "capturas" / f"{repo.agora_utc():%Y%m%d-%H%M%S}"

        def pausar() -> None:
            time.sleep(random.uniform(3, 8))

        with agendador.lock_coleta(engine, ID_LOCK_AMAZON) as obtido:
            if not obtido:
                raise SystemExit("o coletor-amazon está rodando (mesmo perfil do Chromium): docker compose stop coletor-amazon")
            cap = Captura(destino)
            try:
                with NavegadorChromium(config.dir_dados / "perfil-amazon", eh_desafio_amazon) as nav:
                    capturar(nav, args.asin, destino, checkout=args.checkout, pausar=pausar, cap=cap)
                if args.login:
                    with tempfile.TemporaryDirectory() as perfil, NavegadorChromium(Path(perfil), eh_desafio_amazon) as anonimo:
                        cap.salvas.append(capturar_login(anonimo, destino))
            finally:
                # Mesmo com erro (que sobe em seguida): onde ficou e, sobretudo, se o item pode ter ficado no carrinho.
                print(f"capturas em {destino}")
                for caminho in cap.salvas:
                    print(caminho)
                for aviso in cap.avisos:
                    print(f"AVISO: {aviso}")
    elif args.comando == "admin":
        import uvicorn

        from tcg_sniper.admin.app import criar_app

        uvicorn.run(criar_app(sessoes, config), host="0.0.0.0", port=args.porta)
