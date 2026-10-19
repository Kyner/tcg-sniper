import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, EU_SUPERADMIN, ok, renderizarEm } from "../teste/apoio";
import type { Usuario } from "../tipos";

// ids iguais aos de EU_ADMIN (1) e EU_SUPERADMIN (10): a linha de cada um é a "própria"
const ADMIN: Usuario = {
  id: 1, nome: "Pessoa Admin", numero_mascarado: "+55 11 9****-**01", papel: "admin", superadmin: false,
  ativo: true, criado_em: "2026-10-18T13:00:00Z", sessoes_ativas: 1,
};
const SUPER: Usuario = {
  ...ADMIN, id: 10, nome: "Pessoa Superadmin", numero_mascarado: "+55 11 9****-**10", superadmin: true,
};
const GRUPO: Usuario = {
  id: 2, nome: "Pessoa Grupo", numero_mascarado: "+55 11 9****-**02", papel: "grupo", superadmin: false,
  ativo: true, criado_em: "2026-10-18T13:00:00Z", sessoes_ativas: 0,
};
const NOVA: Usuario = { ...GRUPO, id: 9, nome: "Pessoa Nova", numero_mascarado: "+55 11 9****-**09", papel: "operador" };
const OPERADOR_GERE_USUARIOS = { ...EU_OPERADOR, permissoes: [...EU_OPERADOR.permissoes, "gerir_usuarios" as const] };

// O menu do topo também mostra o nome de quem está logado: a linha é a da tabela.
const linhaSincrona = (nome: string) =>
  screen.getAllByText(nome).map((e) => e.closest("tr")).find((tr) => tr !== null)!;
const linhaDe = async (nome: string) => {
  await screen.findByRole("table");
  return linhaSincrona(nome);
};

describe("Gestão → Usuários", () => {
  it("lista com número mascarado e cadastra", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": [ok({ usuarios: [ADMIN, GRUPO] }), ok({ usuarios: [ADMIN, GRUPO, NOVA] })],
      "POST /api/usuarios": { status: 201, corpo: NOVA },
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    expect(await screen.findByText("+55 11 9****-**02")).toBeInTheDocument();
    await usuario.type(screen.getByLabelText("Nome"), "Pessoa Nova");
    await usuario.type(screen.getByLabelText("Número do WhatsApp"), "(11) 90000-0009");
    await usuario.selectOptions(screen.getByLabelText("Papel"), "operador");
    await usuario.click(screen.getByRole("button", { name: "Cadastrar" }));
    expect(await screen.findByText("Pessoa Nova cadastrado.")).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "POST")?.corpo).toEqual({
      nome: "Pessoa Nova", numero: "(11) 90000-0009", papel: "operador",
    });
    expect(await screen.findByText("+55 11 9****-**09")).toBeInTheDocument();
  });

  it("erro da API aparece (ex.: número já cadastrado)", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN] }),
      "POST /api/usuarios": {
        status: 409, corpo: { erro: "numero_ja_cadastrado", mensagem: "Já existe um usuário com este número." },
      },
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    await usuario.type(await screen.findByLabelText("Nome"), "Outra");
    await usuario.type(screen.getByLabelText("Número do WhatsApp"), "11 90000-0001");
    await usuario.click(screen.getByRole("button", { name: "Cadastrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Já existe um usuário com este número.");
  });

  it.each([
    ["operador com gerir_usuarios", OPERADOR_GERE_USUARIOS],
    ["admin comum", EU_ADMIN],
  ])("%s não vê a opção Admin nem os botões das linhas de admin e do superadmin", async (_nome, eu) => {
    apiFalsa({ "GET /api/auth/eu": ok(eu), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    renderizarEm("/gestao/usuarios");
    const linhaSuper = await linhaDe("Pessoa Superadmin");
    expect(within(linhaSuper).getByText("superadmin")).toBeInTheDocument();
    expect(within(linhaSuper).queryByRole("button")).not.toBeInTheDocument();
    const linhaAdmin = linhaSincrona("Pessoa Admin");
    expect(within(linhaAdmin).queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    const linhaGrupo = linhaSincrona("Pessoa Grupo");
    expect(within(linhaGrupo).getByRole("button", { name: "Editar" })).toBeInTheDocument();
    const opcoes = within(screen.getByLabelText("Papel")).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Grupo", "Operador"]);
  });

  it("admin comum vê Sessões na própria linha (encerra as próprias sessões)", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    renderizarEm("/gestao/usuarios");
    const linhaAdmin = await linhaDe("Pessoa Admin");
    expect(within(linhaAdmin).getByRole("button", { name: "Sessões" })).toBeInTheDocument();
  });

  it("superadmin gere admins e, na própria linha, só muda o nome", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_SUPERADMIN), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linhaAdmin = await linhaDe("Pessoa Admin");
    expect(within(linhaAdmin).getByRole("button", { name: "Editar" })).toBeInTheDocument();
    const opcoes = within(screen.getByLabelText("Papel")).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Grupo", "Operador", "Admin"]);
    const linhaSuper = linhaSincrona("Pessoa Superadmin");
    await usuario.click(within(linhaSuper).getByRole("button", { name: "Editar" }));
    const dialogo = screen.getByRole("dialog");
    expect(within(dialogo).getByLabelText("Papel")).toBeDisabled();
    expect(within(dialogo).getByLabelText(/Ativo/)).toBeDisabled();
    expect(within(dialogo).getByLabelText("Nome")).toBeEnabled();
  });

  it("desativar manda PATCH com ativo false", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN, GRUPO] }),
      "PATCH /api/usuarios/2": ok({ ...GRUPO, ativo: false }),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linha = await linhaDe("Pessoa Grupo");
    await usuario.click(within(linha).getByRole("button", { name: "Editar" }));
    const dialogo = screen.getByRole("dialog");
    await usuario.click(within(dialogo).getByLabelText(/Ativo/));
    await usuario.click(within(dialogo).getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("Alterações salvas.")).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "PATCH")?.corpo).toEqual({ nome: "Pessoa Grupo", papel: "grupo", ativo: false });
  });

  it("sessões: lista e encerra", async () => {
    const sessao = {
      id: 7, aparelho: "Chrome · Windows", criada_em: "2026-10-18T13:00:00Z", ultimo_uso_em: "2026-10-18T14:00:00Z",
      expira_em: "2026-11-17T14:00:00Z", atual: false,
    };
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN, GRUPO] }),
      "GET /api/usuarios/2/sessoes": [ok({ sessoes: [sessao] }), ok({ sessoes: [] })],
      "POST /api/sessoes/7/encerrar": ok({ ok: true }),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linha = await linhaDe("Pessoa Grupo");
    await usuario.click(within(linha).getByRole("button", { name: "Sessões" }));
    expect(await screen.findByText("Chrome · Windows")).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Encerrar" }));
    expect(await screen.findByText("Nenhuma sessão aberta.")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/sessoes/7/encerrar")).toBe(true);
  });

  it("operador sem gerir_usuarios vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao/usuarios");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
