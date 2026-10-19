// Gestão → Acessos: grade papel × permissão. Cada toggle salva na hora (PUT /api/acessos); a coluna do admin é
// travada (o admin tem sempre tudo). A API avisa o grupo admin no WhatsApp a cada mudança.
import { useCallback, useEffect, useState } from "react";
import { chamarApi } from "../api";
import { useSessao } from "../sessao";
import type { GradeAcessos, Papel, Permissao } from "../tipos";

export function Acessos() {
  const { tratarErro, recarregar } = useSessao();
  const [grade, setGrade] = useState<GradeAcessos | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setGrade(await chamarApi<GradeAcessos>("/api/acessos"));
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function trocar(papel: Papel, permissao: Permissao, permitido: boolean) {
    setSalvando(true);
    setMensagem(null);
    setErro(null);
    try {
      const corpo = { mudancas: [{ papel, permissao, permitido }] };
      setGrade(await chamarApi<GradeAcessos>("/api/acessos", { metodo: "PUT", corpo }));
      setMensagem("Salvo. Vale na próxima ação de quem já está logado.");
      await recarregar(); // se a mudança foi no seu papel, o menu muda já
    } catch (e) {
      setErro(tratarErro(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Acessos</h1>
      <p className="text-sm opacity-70">
        O que cada papel pode fazer. O admin tem sempre tudo. Cada mudança vale na hora e avisa o grupo admin no WhatsApp.
      </p>
      {mensagem && (
        <div role="status" className="alert alert-success">
          {mensagem}
        </div>
      )}
      {erro && (
        <div role="alert" className="alert alert-error">
          {erro}
        </div>
      )}
      {grade === null ? (
        <span className="loading loading-spinner" aria-label="Carregando" />
      ) : (
        <div className="overflow-x-auto rounded-box bg-base-100 shadow-sm">
          <table className="table">
            <thead>
              <tr>
                <th>Permissão</th>
                {grade.papeis.map((p) => (
                  <th key={p.papel} className="text-center">
                    {p.rotulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grade.permissoes.map((linha) => (
                <tr key={linha.permissao}>
                  <td>
                    <div className="font-medium">{linha.rotulo}</div>
                    <div className="text-xs opacity-70">{linha.descricao}</div>
                  </td>
                  {grade.papeis.map((p) => (
                    <td key={p.papel} className="text-center">
                      <input
                        type="checkbox"
                        className="toggle toggle-success"
                        aria-label={`${p.rotulo}: ${linha.rotulo}`}
                        checked={linha.valores[p.papel]}
                        disabled={!p.editavel || salvando}
                        onChange={(e) => void trocar(p.papel, linha.permissao, e.target.checked)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
