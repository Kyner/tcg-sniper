// Um grupo de Configurações: collapse do DaisyUI com a frase de propósito, os campos, "Avançado" fechado e a
// caixa "Efeito" (calculada pela API com o que está digitado, 400 ms depois da última tecla).
import { useEffect, useRef, useState } from "react";
import { chamarApi } from "../api";
import { useSessao } from "../sessao";
import type { EfeitoConfig, GrupoConfig as Grupo, ValorConfig } from "../tipos";
import { CampoConfig } from "./CampoConfig";

const DEBOUNCE_MS = 400;

function CaixaEfeito({ efeito }: { efeito: EfeitoConfig }) {
  const classe =
    efeito.nivel === "erro" ? "alert alert-error" : efeito.nivel === "aviso" ? "alert alert-warning" : "alert alert-info";
  return (
    <div role="alert" className={`${classe} alert-vertical items-start text-left`}>
      <p className="font-semibold">Efeito</p>
      {efeito.linhas.map((linha) => (
        <p key={linha}>{linha}</p>
      ))}
      {efeito.barras.map((b) => (
        <div key={b.rotulo} className="w-full">
          <p className="text-xs">
            {b.rotulo}: {b.pct}%
          </p>
          <progress
            className={b.pct >= 100 ? "progress progress-error w-full" : b.pct >= 80 ? "progress progress-warning w-full" : "progress progress-primary w-full"}
            value={Math.min(b.pct, 100)}
            max={100}
          />
        </div>
      ))}
    </div>
  );
}

/** Valor digitado ainda sem sentido para o tipo (vazio, não numérico, hora incompleta): não vale pedir o Efeito. */
function digitacaoValida(grupo: Grupo, valores: Record<string, ValorConfig>): boolean {
  return grupo.campos.every((c) => {
    const v = valores[c.chave];
    if (c.tipo === "int" || c.tipo === "decimal" || c.tipo === "float") {
      return String(v ?? "").trim() !== "" && Number.isFinite(Number(String(v).replace(",", ".")));
    }
    if (c.tipo === "hora") return /^\d{2}:\d{2}$/.test(String(v ?? ""));
    return true;
  });
}

function useEfeito(grupo: Grupo, valores: Record<string, ValorConfig>, ativo: boolean) {
  const { tratarErro } = useSessao();
  const [efeito, setEfeito] = useState<EfeitoConfig | null>(null);
  const sequencia = useRef(0);
  const doGrupo = JSON.stringify(Object.fromEntries(grupo.campos.map((c) => [c.chave, valores[c.chave]])));

  useEffect(() => {
    if (!ativo || !grupo.tem_efeito || !digitacaoValida(grupo, JSON.parse(doGrupo) as Record<string, ValorConfig>)) return;
    const minha = ++sequencia.current;
    const timer = setTimeout(() => {
      chamarApi<EfeitoConfig | null>("/api/gestao/configuracoes/efeito", {
        metodo: "POST",
        corpo: { grupo: grupo.id, valores: JSON.parse(doGrupo) as Record<string, ValorConfig> },
      }).then(
        (r) => { if (minha === sequencia.current) setEfeito(r); },
        (e: unknown) => { if (minha === sequencia.current) tratarErro(e); }, // o Efeito é só um apoio: mantém o último bom
      );
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [ativo, grupo, tratarErro, doGrupo]);

  return efeito;
}

interface Props {
  grupo: Grupo;
  aberto: boolean;
  aoAlternar: () => void;
  valores: Record<string, ValorConfig>;
  erros: Record<string, string>;
  editavel: boolean;
  aoMudar: (chave: string, valor: ValorConfig) => void;
}

export function GrupoConfig({ grupo, aberto, aoAlternar, valores, erros, editavel, aoMudar }: Props) {
  const efeito = useEfeito(grupo, valores, aberto);
  const comuns = grupo.campos.filter((c) => !c.avancado);
  const avancados = grupo.campos.filter((c) => c.avancado);
  const [avancadoAberto, setAvancadoAberto] = useState(false);
  const erroAvancado = avancados.some((c) => erros[c.chave] !== undefined);
  useEffect(() => {
    if (erroAvancado) setAvancadoAberto(true);
  }, [erroAvancado]);

  const campo = (c: Grupo["campos"][number]) => (
    <CampoConfig
      key={c.chave}
      campo={c}
      valor={valores[c.chave]}
      erro={erros[c.chave]}
      editavel={editavel}
      aoMudar={(v) => aoMudar(c.chave, v)}
    />
  );

  return (
    <section id={`grupo-${grupo.id}`} className="collapse collapse-arrow border border-base-300 bg-base-100 scroll-mt-4">
      <input type="checkbox" aria-label={`Abrir ${grupo.titulo}`} checked={aberto} onChange={aoAlternar} />
      <div className="collapse-title">
        <h2 className="font-semibold">{grupo.titulo}</h2>
        <p className="text-sm font-normal text-base-content/70">{grupo.proposito}</p>
      </div>
      <div className="collapse-content space-y-4">
        {aberto && (
          <>
            {comuns.map(campo)}
            {avancados.length > 0 && (
              <div className="collapse collapse-arrow border border-base-300">
                <input
                  type="checkbox"
                  aria-label={`Avançado: ${grupo.titulo}`}
                  checked={avancadoAberto}
                  onChange={() => setAvancadoAberto(!avancadoAberto)}
                />
                <div className="collapse-title text-sm font-medium">Avançado</div>
                <div className="collapse-content space-y-4">{avancadoAberto && avancados.map(campo)}</div>
              </div>
            )}
            {efeito && <CaixaEfeito efeito={efeito} />}
          </>
        )}
      </div>
    </section>
  );
}
