// Quem está logado. Ao abrir, pergunta à API (GET /api/auth/eu); as telas usam `pode()` para esconder o que a
// pessoa não pode (a API confere de novo em toda chamada) e `tratarErro()` para reagir a 401/403/API fora.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiIndisponivel, chamarApi, ErroApi } from "./api";
import type { Eu, Permissao } from "./tipos";

export type EstadoSessao =
  | { estado: "carregando" }
  | { estado: "anonimo" }
  | { estado: "indisponivel" }
  | { estado: "logado"; eu: Eu };

interface ValorSessao {
  sessao: EstadoSessao;
  recarregar: () => Promise<void>;
  definirEu: (eu: Eu) => void;
  sair: () => Promise<void>;
  pode: (permissao: Permissao) => boolean;
  tratarErro: (erro: unknown) => string | null;
}

const ContextoSessao = createContext<ValorSessao | null>(null);

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [sessao, setSessao] = useState<EstadoSessao>({ estado: "carregando" });

  const recarregar = useCallback(async () => {
    try {
      setSessao({ estado: "logado", eu: await chamarApi<Eu>("/api/auth/eu") });
    } catch (erro) {
      const semSessao = erro instanceof ErroApi && erro.status === 401;
      setSessao(semSessao ? { estado: "anonimo" } : { estado: "indisponivel" });
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const definirEu = useCallback((eu: Eu) => setSessao({ estado: "logado", eu }), []);

  const sair = useCallback(async () => {
    try {
      await chamarApi("/api/auth/sair", { metodo: "POST" });
    } catch {
      // sem API a sessão vence sozinha; a tela volta para Entrar do mesmo jeito
    }
    setSessao({ estado: "anonimo" });
  }, []);

  const tratarErro = useCallback(
    (erro: unknown): string | null => {
      if (erro instanceof ApiIndisponivel) {
        setSessao({ estado: "indisponivel" });
        return null;
      }
      if (erro instanceof ErroApi) {
        if (erro.status === 401 && erro.erro === "sem_sessao") {
          setSessao({ estado: "anonimo" });
          return null;
        }
        if (erro.status === 403) void recarregar(); // a permissão pode ter saído: as rotas reagem
        return erro.message;
      }
      return "Erro inesperado. Tente de novo.";
    },
    [recarregar],
  );

  const pode = (permissao: Permissao) => sessao.estado === "logado" && sessao.eu.permissoes.includes(permissao);

  return (
    <ContextoSessao.Provider value={{ sessao, recarregar, definirEu, sair, pode, tratarErro }}>
      {children}
    </ContextoSessao.Provider>
  );
}

export function useSessao(): ValorSessao {
  const valor = useContext(ContextoSessao);
  if (valor === null) throw new Error("useSessao fora do SessaoProvider");
  return valor;
}
