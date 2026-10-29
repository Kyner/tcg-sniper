import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const campo = (o: Record<string, unknown>) => ({
  explicacao: "Explica o campo.", tipo: "int", padrao: 10, minimo: 1, maximo: 5000, opcoes: [], avancado: false,
  vinculo: null, ...o,
});
const GRUPOS = [
  {
    id: "monitor", titulo: "Acompanhar preço (Amazon · monitor)", proposito: "De quanto em quanto tempo relê o preço.",
    tem_efeito: true,
    campos: [
      campo({ chave: "amazon.monitor_janela_inicio", rotulo: "Início do monitor", tipo: "hora", padrao: "08:00", minimo: null, maximo: null, valor: "09:00" }),
      campo({ chave: "amazon.monitor_intervalo_min", rotulo: "Intervalo do monitor", padrao: 60, valor: 1500, vinculo: "menor que a janela" }),
      campo({ chave: "amazon.monitor_esgotado_dias", rotulo: "Dias para dar como esgotado", padrao: 3, valor: 3, avancado: true }),
    ],
  },
  {
    id: "ia-decide", titulo: "IA · o que decide sozinha", proposito: "Se a IA avalia os anúncios.", tem_efeito: true,
    campos: [campo({ chave: "ia.ligado", rotulo: "IA ligada", tipo: "bool", padrao: false, minimo: null, maximo: null, valor: true })],
  },
  {
    id: "ia-modelo", titulo: "IA · modelo", proposito: "Qual modelo avalia.", tem_efeito: false,
    campos: [campo({
      chave: "ia.esforco", rotulo: "Esforço", tipo: "escolha", padrao: "low", minimo: null, maximo: null, valor: "medium",
      opcoes: [{ valor: "low", rotulo: "baixo" }, { valor: "medium", rotulo: "médio" }], avancado: true,
    })],
  },
  {
    id: "liga", titulo: "LigaMagic", proposito: "Como a coleta lê os preços.", tem_efeito: false,
    campos: [campo({ chave: "liga.categorias", rotulo: "Categorias da Liga", tipo: "categorias", padrao: [1], minimo: null, maximo: null, valor: [1, 7] })],
  },
];
const AVISOS = [
  { tipo: "coleta_falhou", titulo: "Coleta falhou", descricao: "A coleta parou.", area: "Liga", destino: "grupo admin", agrupa: true, ligado: true, exemplo: "*Atenção* coleta" },
  { tipo: "ia_teto", titulo: "Teto da IA atingido", descricao: "A IA parou.", area: "IA", destino: "grupo admin", agrupa: false, ligado: false, exemplo: "teto _batido_" },
];
const CONFIG = { grupos: GRUPOS, versoes: { amazon: "v1", ia: "v2", liga: "v3" }, avisos: AVISOS, ia: { chave_configurada: true } };
const base = { "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };
const LER = "GET /api/gestao/configuracoes";
const SALVAR = "PUT /api/gestao/configuracoes";
const EFEITO = "POST /api/gestao/configuracoes/efeito";
const EFEITO_OK = ok({ linhas: ["Lê 24 páginas por dia."], nivel: "info", barras: [] });

afterEach(() => vi.restoreAllMocks());
// O histórico do jsdom é global: cada teste começa numa entrada limpa (sem guarda de teste anterior por baixo).
beforeEach(() => window.history.pushState(null, "", "/"));

async function abrir(caminho = "/gestao/configuracoes", extra: Record<string, unknown> = {}) {
  const chamadas = apiFalsa({ ...base, [LER]: ok(CONFIG), [EFEITO]: EFEITO_OK, ...extra } as never);
  renderizarEm(caminho);
  await screen.findByRole("heading", { name: "Acompanhar preço (Amazon · monitor)" });
  return chamadas;
}
const abrirGrupo = (titulo: string) => userEvent.click(screen.getByRole("checkbox", { name: `Abrir ${titulo}` }));

describe("Configurações", () => {
  it("mostra os grupos fechados com a frase de propósito", async () => {
    await abrir();
    expect(screen.getByText("De quanto em quanto tempo relê o preço.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Intervalo do monitor")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Abrir LigaMagic" }).closest(".collapse")).toBeInTheDocument();
  });

  it("tem menu lateral de grupos e o link profundo ?grupo= abre o grupo", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    expect(await screen.findByLabelText("Intervalo do monitor")).toBeInTheDocument();
    const menu = screen.getByRole("navigation", { name: "Grupos de configurações" });
    expect(within(menu).getByRole("link", { name: "LigaMagic" })).toBeInTheDocument();
  });

  it("campo com rótulo, tooltip, Padrão com milhar, vínculo, e ↺ volta ao padrão", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    expect(entrada).toHaveValue("1500");
    expect(screen.getByText("Padrão: 60")).toBeInTheDocument();
    expect(screen.getByText("menor que a janela")).toBeInTheDocument();
    expect(screen.getByText("= 1.500")).toBeInTheDocument();
    const dica = screen.getByRole("button", { name: "Explicação: Intervalo do monitor" });
    expect(dica.closest(".tooltip")).toHaveAttribute("data-tip", "Explica o campo.");
    await userEvent.click(screen.getByRole("button", { name: "Voltar ao padrão: Intervalo do monitor" }));
    expect(entrada).toHaveValue("60");
    expect(screen.getByText("1 alteração")).toBeInTheDocument();
  });

  it("Avançado fica fechado dentro do grupo e esforço usa os rótulos da API", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await screen.findByLabelText("Intervalo do monitor");
    expect(screen.queryByLabelText("Dias para dar como esgotado")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Avançado: Acompanhar preço (Amazon · monitor)" }));
    expect(screen.getByLabelText("Dias para dar como esgotado")).toBeInTheDocument();
    await abrirGrupo("IA · modelo");
    await userEvent.click(screen.getByRole("checkbox", { name: "Avançado: IA · modelo" }));
    const select = screen.getByLabelText("Esforço");
    expect(within(select).getByRole("option", { name: "médio" })).toBeInTheDocument();
  });

  it("booleano é toggle", async () => {
    await abrir();
    await abrirGrupo("IA · o que decide sozinha");
    const chave = screen.getByRole("checkbox", { name: "IA ligada" });
    expect(chave).toHaveClass("toggle");
    expect(chave).toBeChecked();
  });

  it("chama o Efeito com debounce e mostra no alert (aviso em alert-warning)", async () => {
    const chamadas = await abrir("/gestao/configuracoes?grupo=monitor", {
      [EFEITO]: [EFEITO_OK, ok({ linhas: ["Passa da capacidade."], nivel: "aviso", barras: [{ rotulo: "Uso", pct: 120 }] })],
    });
    expect(await screen.findByText("Lê 24 páginas por dia.")).toBeInTheDocument();
    const efeitos = () => chamadas.filter((c) => c.caminho.endsWith("/efeito"));
    const antes = efeitos().length;
    const entrada = screen.getByLabelText("Intervalo do monitor");
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    expect(efeitos().length).toBe(antes);
    const texto = await screen.findByText("Passa da capacidade.");
    expect(texto.closest("[role=alert]")).toHaveClass("alert-warning");
    expect(efeitos().length).toBe(antes + 1);
    expect((efeitos().at(-1)!.corpo as { grupo: string }).grupo).toBe("monitor");
  });

  it("barra fixa: N alterações, Descartar e Salvar mandando só os alterados com as versões", async () => {
    const chamadas = await abrir("/gestao/configuracoes?grupo=monitor", {
      [SALVAR]: ok({ ...CONFIG, versoes: { amazon: "v9", ia: "v2", liga: "v3" } }),
    });
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    expect(screen.queryByRole("button", { name: "Salvar" })).not.toBeInTheDocument();
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    expect(screen.getByText("1 alteração")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(entrada).toHaveValue("1500");
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Salvar" })).not.toBeInTheDocument());
    const put = chamadas.find((c) => c.metodo === "PUT")!;
    expect(put.corpo).toEqual({
      versoes: { amazon: "v1", ia: "v2", liga: "v3" }, valores: { "amazon.monitor_intervalo_min": "30" },
    });
  });

  it("422 mostra o erro junto ao campo, mesmo de grupo fechado, e abre o grupo", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor", {
      [SALVAR]: { status: 422, corpo: { erro: "validacao", mensagem: "Confira os campos marcados.", campos: { "liga.categorias": "Escolha ao menos uma categoria." } } },
    });
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("Escolha ao menos uma categoria.")).toBeInTheDocument();
  });

  it("409 pede para recarregar", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor", {
      [SALVAR]: { status: 409, corpo: { erro: "config_mudou", mensagem: "As configurações mudaram desde que você abriu a tela; recarregue." } },
    });
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("As configurações mudaram; recarregue")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recarregar" })).toBeInTheDocument();
  });

  it("sair com alteração pede confirmação", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.type(entrada, "1");
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(screen.getAllByRole("link", { name: "Atividade" })[0]);
    expect(confirma).toHaveBeenCalled();
    expect(screen.getByLabelText("Intervalo do monitor")).toBeInTheDocument();
  });

  it("Voltar com alteração pergunta e fica se cancelar", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.type(entrada, "1");
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(false);
    const empilha = vi.spyOn(window.history, "pushState");
    window.history.back();
    await waitFor(() => expect(confirma).toHaveBeenCalled());
    expect(empilha).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Intervalo do monitor")).toHaveValue("15001");
    expect(screen.getByRole("button", { name: "Salvar" })).toBeInTheDocument();
  });

  it("Voltar com alteração e confirmar sai", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await userEvent.type(await screen.findByLabelText("Intervalo do monitor"), "1");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const volta = vi.spyOn(window.history, "back");
    window.history.back();
    await waitFor(() => expect(volta).toHaveBeenCalledTimes(2));
  });

  it("depois de confirmar a saída, o navegador não pergunta de novo (beforeunload)", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await userEvent.type(await screen.findByLabelText("Intervalo do monitor"), "1");
    const antes = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(antes);
    expect(antes.defaultPrevented).toBe(true); // com alteração, fechar a aba pergunta
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(true);
    window.history.back();
    await waitFor(() => expect(confirma).toHaveBeenCalled());
    const depois = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(depois);
    expect(depois.defaultPrevented).toBe(false);
  });

  it("fragmento (#avisos) com alteração não é tratado como Voltar", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await userEvent.type(await screen.findByLabelText("Intervalo do monitor"), "1");
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(false);
    window.history.pushState(null, "", "#avisos");
    fireEvent.popState(window);
    expect(confirma).not.toHaveBeenCalled();
  });

  it("a guarda preserva o estado do roteador (idx/key)", async () => {
    window.history.replaceState({ idx: 3, key: "k3", usr: null }, "");
    await abrir("/gestao/configuracoes?grupo=monitor");
    await userEvent.type(await screen.findByLabelText("Intervalo do monitor"), "1");
    expect(window.history.state).toMatchObject({ idx: 3, key: "k3", guardaSair: true });
  });

  it("confirmar a saída por link sai da guarda antes de navegar", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await userEvent.type(await screen.findByLabelText("Intervalo do monitor"), "1");
    expect(window.history.state?.guardaSair).toBe(true);
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(true);
    await userEvent.click(screen.getAllByRole("link", { name: "Atividade" })[0]);
    await waitFor(() => expect(screen.queryByLabelText("Intervalo do monitor")).not.toBeInTheDocument());
    expect(confirma).toHaveBeenCalledTimes(1);
    expect(window.history.state?.guardaSair).toBeFalsy();
  });

  it("Voltar sem alteração não pergunta", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor");
    await screen.findByLabelText("Intervalo do monitor");
    const confirma = vi.spyOn(window, "confirm");
    fireEvent.popState(window);
    expect(confirma).not.toHaveBeenCalled();
  });

  it("operador sem editar vê tudo só leitura e sem barra", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }), [LER]: ok(CONFIG), [EFEITO]: EFEITO_OK });
    renderizarEm("/gestao/configuracoes?grupo=monitor");
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    expect(entrada).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Voltar ao padrão: Intervalo do monitor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Salvar" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Ligar aviso Coleta falhou" })).toBeDisabled();
  });

  it("categorias são chips 'categoria N' com busca e remoção", async () => {
    await abrir("/gestao/configuracoes?grupo=liga");
    expect(await screen.findByText("categoria 7")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remover categoria 7" }));
    expect(screen.queryByText("categoria 7")).not.toBeInTheDocument();
    expect(screen.getByText("1 alteração")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Adicionar categoria"), "9{Enter}");
    expect(screen.getByText("categoria 9")).toBeInTheDocument();
  });

  it("categoria inválida ou repetida avisa o motivo e mantém o texto", async () => {
    await abrir("/gestao/configuracoes?grupo=liga");
    expect(await screen.findByText("categoria 7")).toBeInTheDocument();
    const campo = screen.getByLabelText("Adicionar categoria");
    await userEvent.type(campo, "abc{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("Informe o número da categoria.");
    expect(campo).toHaveValue("abc");
    await userEvent.clear(campo);
    await userEvent.type(campo, "7{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("A categoria 7 já está na lista.");
    await userEvent.type(campo, "1");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("avisos agrupados por área, com busca, toggle no lugar e exemplo ao tocar", async () => {
    const chamadas = await abrir("/gestao/configuracoes", {
      "PATCH /api/gestao/avisos/ia_teto": ok({ ...AVISOS[1], ligado: true }),
    });
    expect(screen.getByRole("heading", { name: "Liga" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "IA" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Buscar aviso"), "teto");
    expect(screen.queryByText("Coleta falhou")).not.toBeInTheDocument();
    const chave = screen.getByRole("checkbox", { name: "Ligar aviso Teto da IA atingido" });
    expect(chave).not.toBeChecked();
    await userEvent.click(chave);
    await waitFor(() => expect(chave).toBeChecked());
    expect(chamadas.find((c) => c.metodo === "PATCH")!.corpo).toEqual({ ligado: true });
    await userEvent.click(screen.getByRole("button", { name: "Ver exemplo: Teto da IA atingido" }));
    expect(screen.getByText("batido").tagName).toBe("EM");
  });

  it("ligar aviso depois de salvar mantém as versões do salvamento", async () => {
    const chamadas = await abrir("/gestao/configuracoes?grupo=monitor", {
      [SALVAR]: ok({ ...CONFIG, versoes: { amazon: "v9", ia: "v2", liga: "v3" } }),
      "PATCH /api/gestao/avisos/ia_teto": ok({ ...AVISOS[1], ligado: true }),
    });
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.clear(entrada);
    await userEvent.type(entrada, "30");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Salvar" })).not.toBeInTheDocument());
    const chave = screen.getByRole("checkbox", { name: "Ligar aviso Teto da IA atingido" });
    await userEvent.click(chave);
    await waitFor(() => expect(chave).toBeChecked());
    await userEvent.clear(screen.getByLabelText("Intervalo do monitor"));
    await userEvent.type(screen.getByLabelText("Intervalo do monitor"), "40");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(chamadas.filter((c) => c.metodo === "PUT")).toHaveLength(2));
    expect((chamadas.filter((c) => c.metodo === "PUT")[1].corpo as { versoes: unknown }).versoes).toEqual({ amazon: "v9", ia: "v2", liga: "v3" });
  });

  it("Recarregar após 409 confirma quando há alterações", async () => {
    await abrir("/gestao/configuracoes?grupo=monitor", {
      [SALVAR]: { status: 409, corpo: { erro: "config_mudou", mensagem: "x" } },
    });
    const entrada = await screen.findByLabelText("Intervalo do monitor");
    await userEvent.type(entrada, "1");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    const confirma = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(await screen.findByRole("button", { name: "Recarregar" }));
    expect(confirma).toHaveBeenCalled();
    expect(screen.getByLabelText("Intervalo do monitor")).toHaveValue("15001");
  });
});
