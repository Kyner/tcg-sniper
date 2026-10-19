import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, EU_OPERADOR, ok, renderizarEm, SEM_SESSAO } from "../teste/apoio";

const PEDIDO_OK = ok({ ok: true, mensagem: "Se o número estiver cadastrado, o código chega no WhatsApp em instantes." });

async function pedirCodigo(numero = "11 90000-0002") {
  const usuario = userEvent.setup();
  await usuario.type(await screen.findByLabelText("Número do WhatsApp"), numero);
  await usuario.click(screen.getByRole("button", { name: "Receber código" }));
  return usuario;
}

describe("Entrar", () => {
  it("número, código e entra na área de negócio", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": ok(EU_GRUPO),
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    expect(await screen.findByText(/o código chega no WhatsApp/)).toBeInTheDocument();
    expect(screen.getByText(/pode demorar/)).toBeInTheDocument();
    await usuario.type(screen.getByLabelText("Código"), "123456");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
    const entrar = chamadas.find((c) => c.caminho === "/api/auth/entrar");
    expect(entrar?.corpo).toEqual({ numero: "11 90000-0002", codigo: "123456" });
  });

  it("quem só tem a gestão cai na gestão depois de entrar", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": ok({ ...EU_OPERADOR, permissoes: ["ver_area_gestao"] }),
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.type(await screen.findByLabelText("Código"), "123456");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Gestão" })).toBeInTheDocument();
  });

  it("código errado mostra a mensagem da API e continua na tela", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": {
        status: 401,
        corpo: { erro: "codigo_invalido", mensagem: "Código errado, vencido ou já usado. Peça um novo." },
      },
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.type(await screen.findByLabelText("Código"), "000000");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Código errado, vencido ou já usado.");
    expect(screen.getByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("limite de pedidos mostra a mensagem e fica no número", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": {
        status: 429,
        corpo: { erro: "limite", mensagem: "Muitos pedidos de código. Espere alguns minutos e tente de novo." },
      },
    });
    renderizarEm("/entrar");
    await pedirCodigo();
    expect(await screen.findByRole("alert")).toHaveTextContent("Muitos pedidos de código.");
    expect(screen.getByLabelText("Número do WhatsApp")).toBeInTheDocument();
  });

  it("Usar outro número volta para o primeiro passo", async () => {
    apiFalsa({ "GET /api/auth/eu": SEM_SESSAO, "POST /api/auth/pedir-codigo": PEDIDO_OK });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.click(await screen.findByRole("button", { name: "Usar outro número" }));
    expect(screen.getByLabelText("Número do WhatsApp")).toHaveValue("11 90000-0002");
  });

  it("já logado, /entrar vai direto para o início", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/entrar");
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
  });
});
