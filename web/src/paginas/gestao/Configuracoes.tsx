// Gestão: Configurações. Grupos que abrem e fecham, cada um com a frase de propósito e a caixa "Efeito"; barra fixa
// com Descartar/Salvar (só para quem pode editar); avisos do WhatsApp ao fim. Salvar manda só o que mudou, com as
// versões lidas (409: alguém salvou antes). Sair com alteração pede confirmação.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { AvisosConfig } from "../../componentes/AvisosConfig";
import { iguais } from "../../componentes/CampoConfig";
import { Carregando } from "../../componentes/Carregando";
import { GrupoConfig } from "../../componentes/GrupoConfig";
import { useSessao } from "../../sessao";
import type { AvisoConfig, Configuracoes as Dados, ValorConfig } from "../../tipos";

const URL = "/api/gestao/configuracoes";
const MENSAGEM_SAIR = "Há alterações não salvas. Sair mesmo assim?";

function valoresDe(dados: Dados): Record<string, ValorConfig> {
  return Object.fromEntries(dados.grupos.flatMap((g) => g.campos.map((c) => [c.chave, c.valor])));
}

/** Avisa antes de perder alterações: fechar/recarregar a aba (beforeunload) e clicar em link interno. O app usa
 * BrowserRouter (sem roteador de dados), onde `useBlocker` não funciona; o botão Voltar do navegador não é coberto. */
function useAvisarAoSair(sujo: boolean) {
  useEffect(() => {
    if (!sujo) return;
    const aoFechar = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const aoClicar = (e: MouseEvent) => {
      const link = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || link.target === "_blank" || link.origin !== window.location.origin) return;
      if (link.pathname === window.location.pathname) return;
      if (!window.confirm(MENSAGEM_SAIR)) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", aoFechar);
    document.addEventListener("click", aoClicar, true);
    return () => {
      window.removeEventListener("beforeunload", aoFechar);
      document.removeEventListener("click", aoClicar, true);
    };
  }, [sujo]);
}

export function Configuracoes() {
  const { pode, tratarErro } = useSessao();
  const editavel = pode("editar_configuracoes");
  const [params] = useSearchParams();
  const profundo = params.get("grupo");
  const [dados, setDados] = useState<Dados | null>(null);
  const [rascunho, setRascunho] = useState<Record<string, ValorConfig>>({});
  const [abertos, setAbertos] = useState<Set<string>>(() => new Set(profundo ? [profundo] : []));
  const [erros, setErros] = useState<Record<string, string>>({});
  const [erroGeral, setErroGeral] = useState<string | null>(null);
  const [mudou, setMudou] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [falhaCarga, setFalhaCarga] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setFalhaCarga(null);
    try {
      const d = await chamarApi<Dados>(URL);
      setDados(d);
      setRascunho(valoresDe(d));
      setErros({});
      setErroGeral(null);
      setMudou(false);
    } catch (e) {
      setFalhaCarga(tratarErro(e));
    }
  }, [tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  // Link profundo: depois de carregar, rola até o grupo pedido.
  useEffect(() => {
    if (dados && profundo) document.getElementById(`grupo-${profundo}`)?.scrollIntoView?.({ block: "start" });
  }, [dados, profundo]);

  const originais = useMemo(() => (dados ? valoresDe(dados) : {}), [dados]);
  const alterados = Object.keys(rascunho).filter((k) => !iguais(rascunho[k], originais[k]));
  useAvisarAoSair(alterados.length > 0);

  if (dados === null) {
    return falhaCarga ? (
      <div role="alert" className="alert alert-error">
        <span>{falhaCarga}</span>
        <button type="button" className="btn btn-sm" onClick={() => void carregar()}>
          Tentar de novo
        </button>
      </div>
    ) : (
      <Carregando />
    );
  }

  const alternar = (id: string) =>
    setAbertos((antes) => {
      const depois = new Set(antes);
      if (!depois.delete(id)) depois.add(id);
      return depois;
    });

  const irPara = (id: string) => {
    setAbertos((antes) => new Set(antes).add(id));
    document.getElementById(`grupo-${id}`)?.scrollIntoView?.({ block: "start" });
  };

  const mudar = (chave: string, valor: ValorConfig) => {
    setRascunho((antes) => ({ ...antes, [chave]: valor }));
    setErros(({ [chave]: _tirado, ...resto }) => resto);
  };

  const salvar = async () => {
    setSalvando(true);
    setErroGeral(null);
    setMudou(false);
    try {
      const novo = await chamarApi<Dados>(URL, {
        metodo: "PUT",
        corpo: { versoes: dados.versoes, valores: Object.fromEntries(alterados.map((k) => [k, rascunho[k]])) },
      });
      setDados(novo);
      setRascunho(valoresDe(novo));
      setErros({});
    } catch (e) {
      if (e instanceof ErroApi && e.status === 409) {
        setMudou(true);
      } else if (e instanceof ErroApi && e.status === 422 && e.campos) {
        const campos = e.campos;
        setErros(campos);
        setErroGeral(e.message);
        // Abre o grupo de qualquer campo com erro (o erro pode vir de um campo que a pessoa não mexeu).
        const comErro = dados.grupos.filter((g) => g.campos.some((c) => campos[c.chave] !== undefined)).map((g) => g.id);
        setAbertos((antes) => new Set([...antes, ...comErro]));
      } else {
        setErroGeral(tratarErro(e));
      }
    } finally {
      setSalvando(false);
    }
  };

  const atualizarAviso = (aviso: AvisoConfig) =>
    setDados({ ...dados, avisos: dados.avisos.map((a) => (a.tipo === aviso.tipo ? aviso : a)) });

  return (
    <div className="space-y-4 pb-20">
      <h1 className="text-2xl font-bold">Configurações</h1>
      {!editavel && (
        <div role="status" className="alert alert-info">
          Você pode ver as configurações, mas não alterá-las.
        </div>
      )}
      {mudou && (
        <div role="alert" className="alert alert-warning">
          <span>As configurações mudaram; recarregue</span>
          <button type="button" className="btn btn-sm" onClick={() => void carregar()}>
            Recarregar
          </button>
        </div>
      )}
      {erroGeral && (
        <div role="alert" className="alert alert-error">
          {erroGeral}
        </div>
      )}
      {!dados.ia.chave_configurada && (
        <div role="status" className="alert alert-warning">
          A chave da OpenAI não está configurada: a IA não consegue avaliar anúncios.
        </div>
      )}
      <div className="lg:flex lg:gap-6">
        <nav aria-label="Grupos de configurações" className="hidden shrink-0 lg:sticky lg:top-4 lg:block lg:w-64 lg:self-start">
          <ul className="menu rounded-box bg-base-100">
            {dados.grupos.map((g) => (
              <li key={g.id}>
                <a
                  href={`#grupo-${g.id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    irPara(g.id);
                  }}
                >
                  {g.titulo}
                </a>
              </li>
            ))}
            <li>
              <a href="#avisos">Avisos do WhatsApp</a>
            </li>
          </ul>
        </nav>
        <div className="min-w-0 flex-1 space-y-3">
          {dados.grupos.map((g) => (
            <GrupoConfig
              key={g.id}
              grupo={g}
              aberto={abertos.has(g.id)}
              aoAlternar={() => alternar(g.id)}
              valores={rascunho}
              erros={erros}
              editavel={editavel}
              aoMudar={mudar}
            />
          ))}
          <AvisosConfig avisos={dados.avisos} editavel={editavel} aoAtualizar={atualizarAviso} />
        </div>
      </div>
      {editavel && alterados.length > 0 && (
        <section
          aria-label="Alterações"
          className="sticky bottom-0 z-10 flex items-center justify-between gap-2 rounded-box border border-base-300 bg-base-100 p-3 shadow"
        >
          <span>
            {alterados.length} {alterados.length === 1 ? "alteração" : "alterações"}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={salvando}
              onClick={() => {
                setRascunho(originais);
                setErros({});
                setErroGeral(null);
              }}
            >
              Descartar
            </button>
            <button type="button" className="btn btn-primary" disabled={salvando} onClick={() => void salvar()}>
              Salvar
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
