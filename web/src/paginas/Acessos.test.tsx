import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../teste/apoio";
import type { GradeAcessos } from "../tipos";

function grade(gestaoParaGrupo: boolean): GradeAcessos {
  return {
    papeis: [
      { papel: "grupo", rotulo: "Grupo", editavel: true },
      { papel: "operador", rotulo: "Operador", editavel: true },
      { papel: "admin", rotulo: "Admin", editavel: false },
    ],
    permissoes: [
      {
        permissao: "ver_area_gestao",
        rotulo: "Entrar na área de gestão",
        descricao: "Ver o menu e as telas da área administrativa.",
        valores: { grupo: gestaoParaGrupo, operador: true, admin: true },
      },
    ],
  };
}

describe("Gestão → Acessos", () => {
  it("coluna do admin travada; toggle manda PUT e mostra o novo valor", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/acessos": ok(grade(false)),
      "PUT /api/acessos": ok(grade(true)),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/acessos");
    const admin = await screen.findByLabelText("Admin: Entrar na área de gestão");
    expect(admin).toBeChecked();
    expect(admin).toBeDisabled();
    const grupo = screen.getByLabelText("Grupo: Entrar na área de gestão");
    expect(grupo).not.toBeChecked();
    await usuario.click(grupo);
    expect(await screen.findByText("Salvo. Vale na próxima ação de quem já está logado.")).toBeInTheDocument();
    expect(screen.getByLabelText("Grupo: Entrar na área de gestão")).toBeChecked();
    expect(chamadas.find((c) => c.metodo === "PUT")?.corpo).toEqual({
      mudancas: [{ papel: "grupo", permissao: "ver_area_gestao", permitido: true }],
    });
  });

  it("operador sem gerir_acessos vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao/acessos");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
