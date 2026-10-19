// Login em dois passos: número → código que chega no WhatsApp → entrar (a API grava o cookie de sessão).
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { chamarApi } from "../api";
import { BotaoTema } from "../componentes/BotaoTema";
import { Carregando } from "../componentes/Carregando";
import { paginaInicial } from "../permissoes";
import { useSessao } from "../sessao";
import type { Eu } from "../tipos";

export function Entrar() {
  const { sessao, definirEu, tratarErro } = useSessao();
  const navegar = useNavigate();
  const [etapa, setEtapa] = useState<"numero" | "codigo">("numero");
  const [numero, setNumero] = useState("");
  const [codigo, setCodigo] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  if (sessao.estado === "carregando") return <Carregando />;
  if (sessao.estado === "logado") return <Navigate to={paginaInicial(sessao.eu.permissoes)} replace />;

  async function pedirCodigo(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const resposta = await chamarApi<{ mensagem: string }>("/api/auth/pedir-codigo", {
        metodo: "POST",
        corpo: { numero },
      });
      setAviso(resposta.mensagem);
      setCodigo("");
      setEtapa("codigo");
    } catch (e) {
      setErro(tratarErro(e));
    } finally {
      setEnviando(false);
    }
  }

  async function entrar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const eu = await chamarApi<Eu>("/api/auth/entrar", { metodo: "POST", corpo: { numero, codigo } });
      definirEu(eu);
      navegar(paginaInicial(eu.permissoes), { replace: true });
    } catch (e) {
      setErro(tratarErro(e));
      setEnviando(false);
    }
  }

  /** Volta ao primeiro passo mantendo o número digitado e sem o erro do código anterior. */
  function usarOutroNumero() {
    setErro(null);
    setEtapa("numero");
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-base-200 p-4">
      <div className="card w-full max-w-sm bg-base-100 shadow-md">
        <div className="card-body gap-4">
          <div className="flex items-center justify-between">
            <h1 className="card-title text-2xl">Entrar</h1>
            <BotaoTema />
          </div>
          {erro && (
            <div role="alert" className="alert alert-error">
              {erro}
            </div>
          )}
          {etapa === "numero" ? (
            <form onSubmit={pedirCodigo} className="flex flex-col gap-4">
              <fieldset className="fieldset">
                <label className="fieldset-legend" htmlFor="numero">
                  Número do WhatsApp
                </label>
                <input
                  id="numero"
                  className="input w-full"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="(11) 9XXXX-XXXX"
                  required
                  maxLength={30}
                  value={numero}
                  onChange={(e) => setNumero(e.target.value)}
                />
              </fieldset>
              <button type="submit" className="btn btn-primary" disabled={enviando}>
                Receber código
              </button>
            </form>
          ) : (
            <form onSubmit={entrar} className="flex flex-col gap-4">
              <div role="status" className="alert alert-info">
                <span>
                  {aviso} Se o WhatsApp estiver fora do ar, o código pode demorar; um admin consegue gerar um código
                  pelo terminal.
                </span>
              </div>
              <fieldset className="fieldset">
                <label className="fieldset-legend" htmlFor="codigo">
                  Código
                </label>
                <input
                  id="codigo"
                  className="input w-full"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  autoFocus
                  value={codigo}
                  onChange={(e) => setCodigo(e.target.value)}
                />
              </fieldset>
              <button type="submit" className="btn btn-primary" disabled={enviando}>
                Entrar
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={usarOutroNumero}>
                Usar outro número
              </button>
            </form>
          )}
        </div>
      </div>
    </main>
  );
}
