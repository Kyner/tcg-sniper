// Ajudantes dos testes: API falsa (troca o fetch) e renderização do app numa rota.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { Rotas } from "../App";
import { SessaoProvider } from "../sessao";
import type { Eu } from "../tipos";

export type RespostaFalsa = { status: number; corpo?: unknown } | "rede-fora";

export interface Chamada {
  metodo: string;
  caminho: string;
  corpo: unknown;
  credenciais: RequestCredentials | undefined;
}

export const ok = (corpo: unknown): RespostaFalsa => ({ status: 200, corpo });

export const SEM_SESSAO: RespostaFalsa = {
  status: 401,
  corpo: { erro: "sem_sessao", mensagem: "Entre de novo para continuar." },
};

/** Responde cada "MÉTODO /caminho" com a resposta dada (lista: uma por chamada, a última se repete). */
export function apiFalsa(respostas: Record<string, RespostaFalsa | RespostaFalsa[]>): Chamada[] {
  const chamadas: Chamada[] = [];
  const fetchFalso = vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
    const caminho = String(entrada);
    const metodo = init?.method ?? "GET";
    const corpo = init?.body ? JSON.parse(String(init.body)) : undefined;
    chamadas.push({ metodo, caminho, corpo, credenciais: init?.credentials });
    const registrada = respostas[`${metodo} ${caminho}`];
    if (registrada === undefined) throw new Error(`teste sem resposta falsa para ${metodo} ${caminho}`);
    const resposta = Array.isArray(registrada)
      ? registrada.length > 1
        ? registrada.shift()!
        : registrada[0]
      : registrada;
    if (resposta === "rede-fora") throw new TypeError("Failed to fetch");
    const texto = resposta.corpo === undefined ? null : JSON.stringify(resposta.corpo);
    return new Response(texto, { status: resposta.status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchFalso);
  return chamadas;
}

export function renderizarEm(caminho: string) {
  return render(
    <SessaoProvider>
      <MemoryRouter initialEntries={[caminho]}>
        <Rotas />
      </MemoryRouter>
    </SessaoProvider>,
  );
}

export const EU_GRUPO: Eu = {
  id: 2,
  nome: "Pessoa Grupo",
  papel: "grupo",
  superadmin: false,
  permissoes: ["ver_area_negocio"],
};
export const EU_OPERADOR: Eu = {
  id: 3,
  nome: "Pessoa Operador",
  papel: "operador",
  superadmin: false,
  permissoes: ["ver_area_negocio", "ver_area_gestao"],
};
/** Admin comum: gere operador e grupo, não mexe em admins. */
export const EU_ADMIN: Eu = {
  id: 1,
  nome: "Pessoa Admin",
  papel: "admin",
  superadmin: false,
  permissoes: ["ver_area_negocio", "ver_area_gestao", "gerir_usuarios", "gerir_acessos", "ver_documentacao_api"],
};
/** O dono do sistema: o único que mexe em admins. */
export const EU_SUPERADMIN: Eu = { ...EU_ADMIN, id: 10, nome: "Pessoa Superadmin", superadmin: true };
