// Dashboard da gestão: o que precisa de você, a saúde dos serviços, as melhores oportunidades e o funil.
// Cada bloco só aparece se a API o mandou (null = sem permissão); a tela se atualiza em silêncio a cada 60 s.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../api";
import { Carregando } from "../componentes/Carregando";
import { Foto } from "../componentes/Foto";
import { SeloEstado } from "../componentes/SeloEstado";
import { enderecoAdminAntigo } from "../enderecos";
import { useSessao } from "../sessao";
import type { DashboardGestao, FunilGestao } from "../tipos";

const RECARGA_MS = 60_000;
const PREFIXO_ANTIGO = "antigo:";

const FUNIL: readonly (readonly [keyof FunilGestao, string, string])[] = [
  ["liga", "Na Liga", "/gestao/catalogo"],
  ["monitorados", "Monitorados", "/gestao/catalogo?monitorado=sim"],
  ["esperando_decisao", "Esperando decisão", "/gestao/casamentos?situacao=esperando_decisao"],
  ["so_ignorados", "Só ignorados", "/gestao/casamentos?situacao=so_ignorados"],
  ["sem_candidato", "Sem candidato", "/gestao/casamentos?situacao=sem_candidato"],
  ["casados_produtos", "Produtos casados", "/gestao/casamentos?situacao=casado"],
  ["casados_anuncios", "Anúncios casados", "/gestao/casamentos?situacao=casado"],
  ["oportunidades", "Oportunidades abertas", "/"],
];

function porcento(v: number): string {
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

export function Gestao() {
  const { tratarErro } = useSessao();
  const [dados, setDados] = useState<DashboardGestao | null>(null);

  useEffect(() => {
    let vivo = true;
    const buscar = (silencioso: boolean) =>
      chamarApi<DashboardGestao>("/api/gestao/dashboard").then(
        (r) => { if (vivo) setDados(r); },
        (e: unknown) => { if (!silencioso && vivo) tratarErro(e); },
      );
    void buscar(false);
    const timer = setInterval(() => void buscar(true), RECARGA_MS);
    return () => { vivo = false; clearInterval(timer); };
  }, [tratarErro]);

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      {dados === null ? <Carregando /> : <Blocos dados={dados} />}
    </section>
  );
}

function Blocos({ dados }: { dados: DashboardGestao }) {
  const { precisa, saude, oportunidades, funil } = dados;
  return (
    <>
      {precisa.length > 0 && (
        <div className="card bg-base-100 shadow-sm">
          <div className="card-body">
            <h2 className="card-title">Precisa de você</h2>
            <ul className="space-y-2">
              {precisa.map((p) => (
                <li key={p.texto} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">{p.texto}</span>
                  {p.destino.startsWith(PREFIXO_ANTIGO) ? (
                    <a
                      className="btn btn-primary btn-sm"
                      href={enderecoAdminAntigo(p.destino.slice(PREFIXO_ANTIGO.length).replace(/^\//, ""))}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.rotulo}
                    </a>
                  ) : (
                    <Link className="btn btn-primary btn-sm" to={p.destino}>{p.rotulo}</Link>
                  )}
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
                  <Link to={`/produtos/${o.produto_id}`} className="flex items-center gap-3 rounded p-1 hover:bg-base-200">
                    <Foto src={o.imagem} alt={o.nome} tamanho="p" />
                    <span className="min-w-0 flex-1 truncate">{o.nome}</span>
                    <span className="badge badge-success">{porcento(o.desconto_pct)}</span>
                  </Link>
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
              {FUNIL.map(([chave, rotulo, destino]) => (
                <li key={chave}>
                  <Link to={destino} className="flex justify-between">
                    <span>{rotulo}</span>
                    <span className="font-semibold">{funil[chave]}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
