// Dashboard da gestão: o que precisa de você, a saúde dos serviços, as melhores oportunidades e o funil.
// Cada bloco só aparece se a API o mandou (null = sem permissão); a tela se atualiza em silêncio a cada 60 s.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../api";
import { Carregando } from "../componentes/Carregando";
import { Foto } from "../componentes/Foto";
import { SeloEstado } from "../componentes/SeloEstado";
import { useSessao } from "../sessao";
import type { DashboardGestao, FunilGestao, Permissao } from "../tipos";

const RECARGA_MS = 60_000;

// Cada linha leva à tela dela para quem tem as permissões listadas (a área de negócio pede também ver_area_negocio).
const FUNIL: readonly (readonly [keyof FunilGestao, string, string, readonly Permissao[]])[] = [
  ["liga", "Na Liga", "/gestao/catalogo", ["ver_catalogo"]],
  ["monitorados", "Monitorados", "/gestao/catalogo?monitorado=sim", ["ver_catalogo"]],
  ["esperando_decisao", "Esperando decisão", "/gestao/casamentos?situacao=esperando_decisao", ["revisar_casamentos"]],
  ["so_ignorados", "Só ignorados", "/gestao/casamentos?situacao=so_ignorados", ["revisar_casamentos"]],
  ["sem_candidato", "Sem candidato", "/gestao/casamentos?situacao=sem_candidato", ["revisar_casamentos"]],
  ["casados_produtos", "Produtos casados", "/gestao/casamentos?situacao=casado", ["revisar_casamentos"]],
  ["casados_anuncios", "Anúncios casados", "/gestao/casamentos?situacao=casado", ["revisar_casamentos"]],
  ["oportunidades", "Oportunidades abertas", "/", ["ver_area_negocio", "ver_oportunidades"]],
];

function porcento(v: number): string {
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

export function Gestao() {
  const { tratarErro } = useSessao();
  const [dados, setDados] = useState<DashboardGestao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [recarga, setRecarga] = useState(0);

  useEffect(() => {
    let vivo = true;
    setErro(null);
    chamarApi<DashboardGestao>("/api/gestao/dashboard").then(
      (r) => { if (vivo) setDados(r); },
      (e: unknown) => { const m = tratarErro(e); if (vivo) setErro(m); },
    );
    return () => { vivo = false; };
  }, [recarga, tratarErro]);

  // A cada minuto a tela se atualiza em silêncio: se falhar, segue com o que já tem.
  useEffect(() => {
    let vivo = true;
    const timer = setInterval(() => {
      chamarApi<DashboardGestao>("/api/gestao/dashboard").then((r) => { if (vivo) setDados(r); }, () => undefined);
    }, RECARGA_MS);
    return () => { vivo = false; clearInterval(timer); };
  }, []);

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      {erro !== null && dados === null && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => setRecarga((n) => n + 1)}>Tentar de novo</button>
        </div>
      )}
      {dados === null ? (erro === null ? <Carregando /> : null) : <Blocos dados={dados} recarregar={async () => { setDados(await chamarApi<DashboardGestao>("/api/gestao/dashboard")); }} />}
    </section>
  );
}

function Blocos({ dados, recarregar }: { dados: DashboardGestao; recarregar: () => Promise<void> }) {
  const { pode, tratarErro } = useSessao();
  const { precisa, saude, oportunidades, funil } = dados;
  const [ocupado, setOcupado] = useState(false);
  const [erroAcao, setErroAcao] = useState<string | null>(null);
  // O botão de um item (ex.: "Já conferi" do carrinho): POST e recarrega o Dashboard.
  // O botão fica travado até a recarga terminar (o item some da lista), senão um 2º clique repetiria o POST.
  async function agir(caminho: string) {
    setOcupado(true);
    setErroAcao(null);
    try {
      await chamarApi<unknown>(caminho, { metodo: "POST" });
      await recarregar();
    } catch (e) {
      setErroAcao(tratarErro(e));
    } finally {
      setOcupado(false);
    }
  }
  // Sem item com botão, um erro de ação antigo não faz mais sentido.
  useEffect(() => { if (!precisa.some((p) => p.acao)) setErroAcao(null); }, [precisa]);
  // O produto das oportunidades fica na área de negócio.
  const abreProduto = pode("ver_area_negocio") && pode("ver_oportunidades");
  return (
    <>
      {precisa.length > 0 && (
        <div className="card bg-base-100 shadow-sm">
          <div className="card-body">
            <h2 className="card-title">Precisa de você</h2>
            {erroAcao !== null && (
              <div role="alert" className="alert alert-error"><span>{erroAcao}</span></div>
            )}
            <ul className="space-y-2">
              {precisa.map((p, i) => (
                <li key={`${i}|${p.texto}|${p.destino}`} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">{p.texto}</span>
                  <span className="flex flex-wrap items-center gap-2">
                    {p.acao && pode("pausar_servicos") && (
                      <button type="button" className="btn btn-sm" disabled={ocupado} onClick={() => void agir(p.acao!.caminho)}>
                        {p.acao.rotulo}
                      </button>
                    )}
                    <Link className="btn btn-primary btn-sm" to={p.destino}>{p.rotulo}</Link>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {saude !== null && (
        <div className="card bg-base-100 shadow-sm">
          <div className="card-body">
            <h2 className="card-title">Saúde dos serviços</h2>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {saude.map((s) => (
                <li key={s.id}>
                  <div className="tooltip w-full" data-tip={s.resumo}>
                    <Link to="/gestao/servicos" className="flex items-center justify-between gap-2 rounded p-2 hover:bg-base-200">
                      <span className="truncate font-medium">{s.nome}</span>
                      <span className="hidden sm:inline-flex"><SeloEstado estado={s.estado} /></span>
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {oportunidades !== null && (
        <div className="card bg-base-100 shadow-sm">
          <div className="card-body">
            <h2 className="card-title">Oportunidades</h2>
            <p className="text-sm">
              {oportunidades.abertas} abertas · {oportunidades.alertas_hoje} alertas hoje · {oportunidades.alertas_semana} na semana
            </p>
            <ul className="space-y-2">
              {oportunidades.top.map((o) => (
                <li key={o.produto_id}>
                  {abreProduto ? (
                    <Link to={`/produtos/${o.produto_id}`} className="flex items-center gap-3 rounded p-1 hover:bg-base-200">
                      <Foto src={o.imagem} alt={o.nome} tamanho="p" />
                      <span className="min-w-0 flex-1 truncate">{o.nome}</span>
                      <span className="badge badge-success">{porcento(o.desconto_pct)}</span>
                    </Link>
                  ) : (
                    <div className="flex items-center gap-3 p-1">
                      <Foto src={o.imagem} alt={o.nome} tamanho="p" />
                      <span className="min-w-0 flex-1 truncate">{o.nome}</span>
                      <span className="badge badge-success">{porcento(o.desconto_pct)}</span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {funil !== null && (
        <div className="card bg-base-100 shadow-sm">
          <div className="card-body">
            <h2 className="card-title">Funil</h2>
            <ul className="menu w-full p-0">
              {FUNIL.map(([chave, rotulo, destino, permissoes]) => (
                <li key={chave}>
                  {permissoes.every((p) => pode(p)) ? (
                    <Link to={destino} className="flex justify-between">
                      <span>{rotulo}</span>
                      <span className="font-semibold">{funil[chave]}</span>
                    </Link>
                  ) : (
                    <span className="flex justify-between">
                      <span>{rotulo}</span>
                      <span className="font-semibold">{funil[chave]}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
