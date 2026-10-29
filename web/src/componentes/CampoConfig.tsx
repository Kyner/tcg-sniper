// Um campo de Configurações: rótulo com dica (ⓘ), controle conforme o tipo, "Padrão: X", vínculo, ↺ e erro.
// O valor em edição fica na tela de Configurações; números e horas viajam como texto digitado (a API converte).
import { milhar } from "../formato";
import type { CampoConfig as Campo, ValorConfig } from "../tipos";
import { CategoriasConfig } from "./CategoriasConfig";

/** Dois valores contam como iguais se têm o mesmo texto ("30" e 30; null e ""); listas, na mesma ordem. */
export function iguais(a: ValorConfig, b: ValorConfig): boolean {
  if (Array.isArray(a) || Array.isArray(b)) return JSON.stringify(a) === JSON.stringify(b);
  return String(a ?? "") === String(b ?? "");
}

function mostrarPadrao(campo: Campo): string {
  const v = campo.padrao;
  if (v === null || v === "") return "vazio";
  if (typeof v === "boolean") return v ? "ligado" : "desligado";
  if (Array.isArray(v)) return v.length === 0 ? "nenhuma" : v.map((n) => `categoria ${n}`).join(", ");
  if (campo.tipo === "escolha") return campo.opcoes.find((o) => o.valor === v)?.rotulo ?? String(v);
  if (campo.tipo === "int") return milhar(v);
  return String(v);
}

interface Props {
  campo: Campo;
  valor: ValorConfig;
  erro: string | undefined;
  editavel: boolean;
  aoMudar: (valor: ValorConfig) => void;
}

export function CampoConfig({ campo, valor, erro, editavel, aoMudar }: Props) {
  const id = `campo-${campo.chave}`;
  const numerico = campo.tipo === "int" || campo.tipo === "decimal" || campo.tipo === "float";
  const diferente = !iguais(valor, campo.padrao);
  const texto = valor === null || Array.isArray(valor) ? "" : String(valor);

  let controle;
  if (campo.tipo === "bool") {
    controle = (
      <input
        id={id}
        type="checkbox"
        className="toggle toggle-primary"
        checked={valor === true}
        disabled={!editavel}
        onChange={(e) => aoMudar(e.target.checked)}
      />
    );
  } else if (campo.tipo === "escolha") {
    controle = (
      <select
        id={id}
        className={erro ? "select select-bordered select-error w-full" : "select select-bordered w-full"}
        value={texto}
        disabled={!editavel}
        onChange={(e) => aoMudar(e.target.value)}
      >
        {campo.opcoes.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.rotulo}
          </option>
        ))}
      </select>
    );
  } else if (campo.tipo === "categorias") {
    controle = (
      <CategoriasConfig
        ids={Array.isArray(valor) ? valor : []}
        editavel={editavel}
        aoMudar={aoMudar}
        rotulo={campo.rotulo}
      />
    );
  } else {
    controle = (
      <input
        id={id}
        type={campo.tipo === "hora" ? "time" : "text"}
        inputMode={numerico ? "decimal" : undefined}
        className={erro ? "input input-bordered input-error w-full" : "input input-bordered w-full"}
        value={texto}
        disabled={!editavel}
        onChange={(e) => aoMudar(e.target.value)}
      />
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <label htmlFor={campo.tipo === "categorias" ? undefined : id} className="font-medium">
          {campo.rotulo}
        </label>
        <div className="tooltip tooltip-bottom" data-tip={campo.explicacao}>
          <button type="button" className="btn btn-ghost btn-sm btn-circle" aria-label={`Explicação: ${campo.rotulo}`}>
            ⓘ
          </button>
        </div>
        {editavel && diferente && (
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-circle"
            aria-label={`Voltar ao padrão: ${campo.rotulo}`}
            onClick={() => aoMudar(campo.padrao)}
          >
            ↺
          </button>
        )}
      </div>
      {controle}
      <div className="flex min-w-0 flex-wrap gap-x-3 text-xs text-base-content/70">
        <span className="min-w-0 break-all">Padrão: {mostrarPadrao(campo)}</span>
        {numerico && texto !== "" && Math.abs(Number(texto)) >= 1000 && <span>= {milhar(texto)}</span>}
        {campo.vinculo && <span>{campo.vinculo}</span>}
      </div>
      {erro && <p className="text-sm text-error">{erro}</p>}
    </div>
  );
}
