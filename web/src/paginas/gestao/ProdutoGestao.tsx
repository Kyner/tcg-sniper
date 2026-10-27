// Gestão: um produto da Liga (monitorado ou não) com preços, contagem de casamentos e a curva dos últimos 30 dias.
// A query do catálogo de onde veio fica na URL e serve de destino do "Voltar" quando não há página anterior.
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { BotaoVoltar } from "../../componentes/BotaoVoltar";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { useFiltrosUrl } from "../../filtrosUrl";
import { dataHora, pct, reais } from "../../formato";
import { useSessao } from "../../sessao";
import type { ProdutoGestaoDados } from "../../tipos";
import { NaoEncontrada } from "../NaoEncontrada";
import { montarQueryCatalogo, PADROES_CATALOGO } from "./Catalogo";

// O gráfico (Recharts) é pesado: carrega só quando há curva para mostrar.
const CurvaPreco = lazy(() => import("../../componentes/CurvaPreco").then((m) => ({ default: m.CurvaPreco })));

export function ProdutoGestao() {
  const { id } = useParams();
  const { pode, tratarErro } = useSessao();
  const [filtros] = useFiltrosUrl(PADROES_CATALOGO);
  const [dados, setDados] = useState<ProdutoGestaoDados | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [naoExiste, setNaoExiste] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const query = montarQueryCatalogo(filtros, true);
  const voltar = `/gestao/catalogo${query ? `?${query}` : ""}`;

  useEffect(() => {
    const sinal = { cancelado: false };
    setDados(null); setErro(null); setNaoExiste(false); setAviso(null);
    chamarApi<ProdutoGestaoDados>(`/api/gestao/produtos/${id}`).then(
      (r) => { if (!sinal.cancelado) setDados(r); },
      (e: unknown) => {
        if (sinal.cancelado) return;
        if (e instanceof ErroApi && e.status === 404) setNaoExiste(true);
        else setErro(tratarErro(e));
      },
    );
    return () => { sinal.cancelado = true; };
  }, [id, tratarErro]);

  async function alternar() {
    if (!dados) return;
    const antes = dados.monitorado;
    const pinta = (valor: boolean) => setDados((d) => d && { ...d, monitorado: valor });
    setAviso(null); setOcupado(true); pinta(!antes);
    try {
      await chamarApi(`/api/gestao/produtos/${id}`, { metodo: "PATCH", corpo: { ativo: !antes } });
    } catch (e) {
      pinta(antes);
      setAviso(tratarErro(e) ?? "Não foi possível alterar o produto.");
    } finally {
      setOcupado(false);
    }
  }

  if (naoExiste) return <NaoEncontrada />;
  if (dados === null && !erro) return <Carregando />;
  if (dados === null) {
    return (
      <section className="space-y-3">
        <div role="alert" className="alert alert-error"><span>{erro}</span></div>
        <BotaoVoltar padrao={voltar} />
      </section>
    );
  }

  const { produto, liga, melhor_amazon: amazon, casamentos, curva } = dados;
  return (
    <section className="space-y-4">
      <BotaoVoltar padrao={voltar} />

      <div className="flex flex-wrap items-start gap-4">
        <Foto src={produto.imagem} alt={produto.nome} tamanho="g" />
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="text-2xl font-bold">{produto.nome}</h1>
          {produto.nome_en && produto.nome_en !== produto.nome && <p className="text-sm opacity-70">{produto.nome_en}</p>}
          <p className="text-sm opacity-70">{produto.categoria ?? "Sem categoria"}</p>
          {dados.esgotado_liga && <span className="badge badge-warning">Esgotado na Liga</span>}
          {produto.pistas.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {produto.pistas.map((p) => <span key={p} className="badge badge-outline badge-sm">{p}</span>)}
            </div>
          )}
          {pode("editar_catalogo") ? (
            <label className="label cursor-pointer justify-start gap-3">
              <input type="checkbox" className="toggle toggle-success" aria-label="Monitorar"
                checked={dados.monitorado} disabled={ocupado} onChange={() => void alternar()} />
              <span>{dados.monitorado ? "Monitorado" : "Não monitorado"}</span>
            </label>
          ) : (
            <span className={dados.monitorado ? "badge badge-success" : "badge badge-ghost"}>
              {dados.monitorado ? "Monitorado" : "Não monitorado"}
            </span>
          )}
        </div>
      </div>

      {aviso && (
        <div role="alert" className="alert alert-error">
          <span>{aviso}</span>
          <button type="button" className="btn btn-sm" onClick={() => setAviso(null)}>Fechar</button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-box bg-base-100 p-4 shadow-sm">
          <h2 className="font-semibold">Liga</h2>
          <dl className="mt-2 space-y-1 text-sm">
            <div className="flex justify-between gap-2"><dt>A partir de</dt><dd>{reais(liga.preco)}</dd></div>
            <div className="flex justify-between gap-2"><dt>Preço médio</dt><dd>{reais(liga.medio)}</dd></div>
            <div className="flex justify-between gap-2"><dt>Lojas</dt><dd>{liga.lojas ?? "—"}</dd></div>
            <div className="flex justify-between gap-2"><dt>Lido em</dt><dd>{liga.lido_em ? dataHora(liga.lido_em) : "—"}</dd></div>
          </dl>
        </div>
        <div className="rounded-box bg-base-100 p-4 shadow-sm">
          <h2 className="font-semibold">Amazon</h2>
          {dados.anuncio ? (
            <div className="mt-2 space-y-1 text-sm">
              <a className="link" href={dados.anuncio.url} target="_blank" rel="noreferrer" title={dados.anuncio.titulo}>
                Ver na Amazon
              </a>
              {amazon ? (
                <dl className="space-y-1">
                  <div className="flex justify-between gap-2"><dt>Melhor preço</dt><dd>{reais(amazon.preco)}</dd></div>
                  <div className="flex justify-between gap-2"><dt>Abaixo da Liga</dt><dd>{pct(amazon.diferenca_pct)}</dd></div>
                </dl>
              ) : (
                dados.sem_preco && <p><span className="badge badge-ghost">sem preço agora</span></p>
              )}
              {dados.anuncios_casados > 1 && (
                pode("revisar_casamentos")
                  ? <p><Link className="link" to={`/gestao/casamentos/${produto.id}`}>+{dados.anuncios_casados - 1} anúncios</Link></p>
                  : <p className="opacity-70">+{dados.anuncios_casados - 1} anúncios</p>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm opacity-70">Sem anúncio confirmado</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="badge badge-warning">{casamentos.pendentes} pendentes</span>
        <span className="badge badge-success">{casamentos.confirmados} confirmados</span>
        <span className="badge badge-ghost">{casamentos.ignorados} ignorados</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {pode("revisar_casamentos") && (
          <Link className="btn btn-primary btn-sm" to={`/gestao/casamentos/${produto.id}`}>Revisar este produto</Link>
        )}
        {pode("ver_oportunidades") && (
          <Link className="btn btn-sm" to={`/produtos/${produto.id}`}>Histórico do produto</Link>
        )}
        <a className="btn btn-sm btn-ghost" href={produto.url} target="_blank" rel="noreferrer">Ver na Liga</a>
      </div>

      <section aria-labelledby="titulo-curva" className="space-y-2">
        <h2 id="titulo-curva" className="text-xl font-semibold">Últimos 30 dias</h2>
        {curva ? (
          <Suspense fallback={<Carregando />}>
            <CurvaPreco historico={curva} destaque={null} />
          </Suspense>
        ) : (
          <p className="opacity-70">Ainda não há leituras suficientes para a curva</p>
        )}
      </section>
    </section>
  );
}
