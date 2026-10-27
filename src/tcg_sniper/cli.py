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


def _numero_ou_sair(texto: str) -> str:
    from tcg_sniper.formatacao import normalizar_numero

    try:
        return normalizar_numero(texto)
    except ValueError:
        raise SystemExit('número inválido: use DDD e número, ex.: "(11) 9XXXX-XXXX"') from None


def _segredo_ou_sair(config: Config) -> str:
    """SEGREDO_API do .env (a API e o código de emergência não começam sem ela)."""
    from tcg_sniper.api.segredos import SegredoAusente, exigir_segredo

    try:
        return exigir_segredo(config)
    except SegredoAusente as erro:
        raise SystemExit(str(erro)) from None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tcg-sniper")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("migrate", help="aplica as migrações do banco")
    sub.add_parser("coletor-liga", help="inicia o agendador de coletas da LigaMagic")
    sub.add_parser(
        "coletor-amazon",
        help="inicia o monitor de preço, a conferência de checkout e a retirada do carrinho da Amazon (navegador logado)",
    )
    sub.add_parser(
        "coletor-amazon-busca", help="inicia a fila de buscas de anúncios novos na Amazon (navegador próprio, sem login)"
    )
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
    casamento = sub.add_parser("casamento", help="ferramentas do casamento")
    casamento_sub = casamento.add_subparsers(dest="acao_casamento", required=True)
    reabrir_p = casamento_sub.add_parser(
        "reabrir-ingles",
        help="reabre para a IA reavaliar os pares ignorados pelo automático por serem em inglês (regra de idioma revista)",
    )
    reabrir_p.add_argument("--aplicar", action="store_true", help="aplica (sem ela, só mostra as contagens)")
    idioma_p = casamento_sub.add_parser(
        "definir-idioma",
        help="preenche o idioma dos anúncios confirmados pelo título (o que o título não decide fica listado)",
    )
    idioma_p.add_argument("--aplicar", action="store_true", help="aplica (sem ela, só mostra as contagens)")
    soltar_p = casamento_sub.add_parser(
        "soltar-inativos",
        help="solta os anúncios confirmados de produtos já inativos (a desativação passou a soltar sozinha)",
    )
    soltar_p.add_argument("--aplicar", action="store_true", help="aplica (sem ela, só lista)")
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
    api_p = sub.add_parser("api", help="inicia a API do front novo (JSON, login pelo WhatsApp)")
    api_p.add_argument("--host", default="127.0.0.1", help="no container: 0.0.0.0 (o compose publica só no 127.0.0.1)")
    api_p.add_argument("--porta", type=int, default=8100)
    codigo_p = sub.add_parser(
        "codigo-acesso", help="acesso de emergência: mostra no terminal um código válido (5 min) para o usuário"
    )
    codigo_p.add_argument("numero", help='número de WhatsApp do usuário, ex.: "(11) 9XXXX-XXXX"')
    criar_super_p = sub.add_parser(
        "criar-superadmin", help="cria o superadmin do site novo (o dono do sistema; um só, recusa se já houver)"
    )
    criar_super_p.add_argument("nome")
    criar_super_p.add_argument("numero", help='número de WhatsApp, ex.: "(11) 9XXXX-XXXX"')
    trocar_super_p = sub.add_parser(
        "trocar-superadmin", help="passa o superadmin para outro usuário ativo (o antigo continua admin)"
    )
    trocar_super_p.add_argument("numero", help='número de WhatsApp do usuário, ex.: "(11) 9XXXX-XXXX"')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()

    if args.comando == "migrate":
        migrar(config.database_url)
        return

    engine = criar_engine(config.database_url)
    sessoes = criar_sessoes(engine)

    if args.comando == "coletor-liga":
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.coletor_liga.agendador import Agendador
        from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright

        Batimento(sessoes, "liga").iniciar()
        instalar_sigterm()
        Agendador(
            engine,
            sessoes,
            lambda: NavegadorPlaywright(config.dir_dados / "perfil"),
            criar_avisador(sessoes),
            config,
        ).rodar()
    elif args.comando == "coletor-amazon":
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura_monitor import VarreduraMonitor
        from tcg_sniper.navegador.chromium import NavegadorChromium

        Batimento(sessoes, "amazon").iniciar()
        instalar_sigterm()
        VarreduraMonitor(
            engine,
            sessoes,
            lambda: NavegadorChromium(config.dir_dados / "perfil-amazon", eh_desafio_amazon),
            criar_avisador(sessoes),
            config,
        ).rodar()
    elif args.comando == "coletor-amazon-busca":
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
        from tcg_sniper.db.models import COLETOR_AMAZON_BUSCA
        from tcg_sniper.navegador.chromium import NavegadorChromium

        Batimento(sessoes, COLETOR_AMAZON_BUSCA).iniciar()
        instalar_sigterm()
        VarreduraBusca(
            engine,
            sessoes,
            lambda: NavegadorChromium(config.dir_dados / "perfil-amazon-busca", eh_desafio_amazon),
            criar_avisador(sessoes),
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
    elif args.comando == "casamento":
        from tcg_sniper.db import repositorio_casamento as repo_casamento
        from tcg_sniper.db.repositorio import agora_utc

        if args.acao_casamento == "definir-idioma":
            with sessoes() as s, s.begin():
                resultado = repo_casamento.definir_idioma_confirmados(s, agora_utc(), aplicar=args.aplicar)
            if not args.aplicar:
                print("simulação: nada mudou (use --aplicar para gravar)")
            print("Idioma definido pelo título:")
            for idioma, quantos in sorted(resultado.definidos.items()):
                print(f"  {idioma}: {quantos}")
            if resultado.suspeitos:
                print(f"Atenção, possível casamento errado (japonês/outro idioma confirmado): {len(resultado.suspeitos)}")
                for anuncio_id, titulo in resultado.suspeitos:
                    print(f"  #{anuncio_id} {titulo}")
            print(f"Sem decisão: {len(resultado.sem_decisao)} (defina à mão na revisão de casamentos)")
            for anuncio_id, titulo in resultado.sem_decisao:
                print(f"  #{anuncio_id} {titulo}")
            return
        if args.acao_casamento == "soltar-inativos":
            with sessoes() as s, s.begin():
                produtos = repo_casamento.soltar_inativos(s, agora_utc(), aplicar=args.aplicar)
            if not produtos:
                print("Nenhum produto inativo com anúncio confirmado.")
                return
            if not args.aplicar:
                print("simulação: nada mudou (use --aplicar para soltar)")
            for p in produtos:
                print(f"  #{p.produto_id} {p.nome}: {p.anuncios} anúncio(s), {p.oportunidades} oportunidade(s) aberta(s)")
                if args.aplicar:
                    logging.getLogger(__name__).info("soltar-inativos: produto %s, %s anúncio(s) soltos", p.produto_id, p.anuncios)
            print(f"Produtos: {len(produtos)}; anúncios: {sum(p.anuncios for p in produtos)}")
            return
        with sessoes() as s, s.begin():
            r = repo_casamento.reabrir_ignorados_por_ingles(s, agora_utc(), aplicar=args.aplicar)
        if not args.aplicar:
            print("simulação: nada mudou (use --aplicar para reabrir)")
        print(f"Encontrados: {r.encontrados}")
        print(f"Reabertos: {r.reabertos}")
        print(f"Confirmados em outro produto: {r.confirmados_em_outro}")
    elif args.comando == "amazon":
        import random
        import tempfile
        import time
        from pathlib import Path

        from tcg_sniper.coletor_amazon.captura import Captura, capturar, capturar_login
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura_base import ID_LOCK_AMAZON
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
    elif args.comando == "api":
        import uvicorn

        from tcg_sniper.api.app import criar_app

        _segredo_ou_sair(config)  # mensagem clara no terminal antes de montar o app
        uvicorn.run(criar_app(sessoes, config), host=args.host, port=args.porta)
    elif args.comando == "codigo-acesso":
        from tcg_sniper.api import acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        segredo = _segredo_ou_sair(config)
        numero = _numero_ou_sair(args.numero)
        with sessoes() as s, s.begin():
            usuario = repo_acesso.usuario_por_numero(s, numero)
            if usuario is None or not usuario.ativo:
                raise SystemExit("nenhum usuário ativo com esse número")
            nome = usuario.nome
            codigo = acesso.emitir_codigo(s, usuario.id, agora_utc(), segredo)
        # no terminal de propósito (é o acesso de emergência); nunca no log
        print(f"Código para {nome} ({mascarar_numero(numero)}): {codigo}")
        print("Vale por 5 minutos, uma vez. Digite na tela Entrar.")
    elif args.comando == "criar-superadmin":
        from tcg_sniper.api import avisos_acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        nome = args.nome.strip()
        if not nome:
            raise SystemExit("nome vazio")
        numero = _numero_ou_sair(args.numero)
        agora = agora_utc()
        with sessoes() as s, s.begin():
            try:
                usuario = repo_acesso.criar_superadmin(s, nome, numero, agora)
            except repo_acesso.SuperadminJaExiste:
                raise SystemExit(
                    "já existe um superadmin; para trocar use tcg-sniper trocar-superadmin <número>"
                ) from None
            except repo_acesso.NumeroJaCadastrado:
                raise SystemExit(
                    "este número já é de um usuário; para torná-lo superadmin use tcg-sniper trocar-superadmin <número>"
                ) from None
            avisos_acesso.usuario_criado(s, usuario, "terminal", agora)
        print(
            f"Superadmin {nome} criado ({mascarar_numero(numero)}). Para entrar: peça o código na tela Entrar "
            "ou rode tcg-sniper codigo-acesso com o número."
        )
    elif args.comando == "trocar-superadmin":
        from tcg_sniper.api import avisos_acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        numero = _numero_ou_sair(args.numero)
        agora = agora_utc()
        with sessoes() as s, s.begin():
            # Trava as duas linhas (o atual e o novo) contra uma edição pela API ao mesmo tempo.
            atual = repo_acesso.superadmin_atual(s, travar=True)
            if atual is None:
                raise SystemExit("ainda não há superadmin; use tcg-sniper criar-superadmin <nome> <número>")
            novo = repo_acesso.usuario_por_numero(s, numero, travar=True)
            if novo is None or not novo.ativo:
                raise SystemExit("nenhum usuário ativo com esse número")
            if novo.id == atual.id:
                raise SystemExit("este usuário já é o superadmin")
            try:
                antigo = repo_acesso.trocar_superadmin(s, novo)
            except repo_acesso.TrocaInvalida as erro:
                raise SystemExit(str(erro)) from None
            avisos_acesso.superadmin_trocado(s, novo, antigo, "terminal", agora)
            nome_novo, nome_antigo = novo.nome, antigo.nome
        print(f"Superadmin agora é {nome_novo} ({mascarar_numero(numero)}); {nome_antigo} continua admin.")
