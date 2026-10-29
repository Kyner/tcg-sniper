// Um anúncio da Amazon na revisão de um produto: título com a variação destacada, parecer da IA e as decisões.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { dataHora, reais } from "../formato";
import type { AcaoCasamento, AnuncioRevisao, GrupoRevisao } from "../tipos";
import { Foto } from "./Foto";

// Classes escritas por extenso: o cartão muda de cor ao mudar de grupo.
const CAIXA: Record<GrupoRevisao, string> = {
  para_decidir: "card card-border card-sm bg-base-100",
  confirmados: "card card-border card-sm border-success bg-base-100",
  ignorados: "card card-border card-sm bg-base-200",
};
const CAIXA_SELECIONADA = "card card-border card-sm border-primary bg-base-100";

const ORIGENS: Record<string, string> = {
  manual: "você",
  sugerido_ia: "você (a IA sugeriu)",
  automatico_ia: "automático (IA)",
  outro_confirmado: "outro confirmado",
};

function escapar(texto: string): string {
  return texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** O título com os trechos de variação (Foil, idioma, quantidade) em destaque. */
function Titulo({ titulo, termos }: { titulo: string; termos: string[] }) {
  const validos = termos.filter((t) => t.trim() !== "");
  if (validos.length === 0) return <>{titulo}</>;
  const partes = titulo.split(new RegExp(`(${validos.map(escapar).join("|")})`, "gi"));
  const destacar = new Set(validos.map((t) => t.toLowerCase()));
  const saida: ReactNode[] = partes.map((p, i) =>
    destacar.has(p.toLowerCase()) ? <span key={i} className="font-semibold text-warning">{p}</span> : p,
  );
  return <>{saida}</>;
}

function Parecer({ anuncio }: { anuncio: AnuncioRevisao }) {
  const ia = anuncio.ia;
  if (ia === null) return null;
  const selo = ia.mesmo_produto ? (
    ia.confianca >= 90 ? (
      <span className="badge badge-success badge-sm">IA: mesmo · {ia.confianca}%</span>
    ) : (
      <span className="badge badge-warning badge-sm">IA: mesmo · {ia.confianca}%</span>
    )
  ) : (
    <span className="badge badge-error badge-sm">IA: outro · {ia.confianca}%</span>
  );
  return (
    <div className="flex min-w-0 items-center gap-1">
      {selo}
      {(anuncio.idioma ?? ia.idioma) && (
        <span className="badge badge-outline badge-sm">{anuncio.idioma ?? ia.idioma}</span>
      )}
      <div className="tooltip min-w-0 flex-1" data-tip={ia.motivo}>
        <p className="truncate text-left text-xs opacity-70">{ia.motivo}</p>
      </div>
    </div>
  );
}

const IDIOMAS: { valor: string; rotulo: string }[] = [
  { valor: "pt", rotulo: "português" },
  { valor: "en", rotulo: "inglês" },
  { valor: "ja", rotulo: "japonês" },
  { valor: "outro", rotulo: "outro" },
];

/** Só no confirmado: o selo do idioma (quando o parecer da IA não o mostra) e o menu "definir idioma". */
function DefinirIdioma({
  anuncio,
  onDefinir,
  ocupado,
}: {
  anuncio: AnuncioRevisao;
  onDefinir: (idioma: string) => void;
  ocupado: boolean;
}) {
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);
  // Aberto, o menu fecha com Esc ou com um clique fora dele.
  useEffect(() => {
    if (!aberto) return;
    const tecla = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setAberto(false);
    };
    const clique = (ev: MouseEvent) => {
      if (!(ev.target instanceof Node) || !caixa.current?.contains(ev.target)) setAberto(false);
    };
    document.addEventListener("keydown", tecla);
    document.addEventListener("mousedown", clique);
    return () => {
      document.removeEventListener("keydown", tecla);
      document.removeEventListener("mousedown", clique);
    };
  }, [aberto]);
  const escolher = (idioma: string) => {
    setAberto(false);
    onDefinir(idioma);
  };
  return (
    <div className="flex items-center gap-2">
      {anuncio.ia === null && anuncio.idioma && <span className="badge badge-outline badge-sm">{anuncio.idioma}</span>}
      <div ref={caixa} className={aberto ? "dropdown dropdown-open" : "dropdown"}>
        <button type="button" className="btn btn-ghost btn-sm" disabled={ocupado} onClick={() => setAberto(!aberto)}>
          definir idioma
        </button>
        {aberto && (
          <ul className="menu menu-sm dropdown-content z-10 mt-1 w-40 rounded-box bg-base-100 p-2 shadow">
            {IDIOMAS.map((i) => (
              <li key={i.valor}>
                <button type="button" onClick={() => escolher(i.valor)}>{i.rotulo}</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Situacao({ anuncio, grupo }: { anuncio: AnuncioRevisao; grupo: GrupoRevisao }) {
  if (grupo === "para_decidir") return null;
  const partes: string[] = [];
  if (anuncio.origem) partes.push(`por ${ORIGENS[anuncio.origem] ?? anuncio.origem}`);
  if (anuncio.revisado_em) partes.push(dataHora(anuncio.revisado_em));
  if (anuncio.casado_com) partes.push(`confirmado em ${anuncio.casado_com.nome}`);
  if (grupo === "ignorados" && anuncio.ia) partes.push(anuncio.ia.motivo);
  if (partes.length === 0) return null;
  const texto = partes.join(" · ");
  return (
    <div className="tooltip max-w-full" data-tip={texto}>
      <p className="truncate text-left text-xs opacity-70">{texto}</p>
    </div>
  );
}

export function CartaoAnuncio({
  anuncio,
  grupo,
  onDecidir,
  onDefinirIdioma,
  ocupado,
  selecionado = false,
}: {
  anuncio: AnuncioRevisao;
  grupo: GrupoRevisao;
  onDecidir: (acao: AcaoCasamento) => void;
  onDefinirIdioma?: (idioma: string) => void;
  ocupado: boolean;
  selecionado?: boolean;
}) {
  const caixa = selecionado && grupo === "para_decidir" ? CAIXA_SELECIONADA : CAIXA[grupo];
  return (
    <article className={caixa} aria-current={selecionado ? "true" : undefined}>
      <div className="card-body flex-row gap-3">
        <Foto src={anuncio.imagem} alt={anuncio.titulo} tamanho={grupo === "para_decidir" ? "g" : "m"} />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm">
            <Titulo titulo={anuncio.titulo} termos={anuncio.termos_variacao} />
          </p>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">{reais(anuncio.preco)}</span>
            {anuncio.vendedor && <span className="opacity-70">{anuncio.vendedor}</span>}
            <a className="link text-xs" href={anuncio.url} target="_blank" rel="noreferrer">{anuncio.asin} ↗</a>
            {anuncio.oportunidade && <span className="badge badge-accent badge-sm">oportunidade</span>}
          </div>
          {grupo !== "ignorados" && <Parecer anuncio={anuncio} />}
          <Situacao anuncio={anuncio} grupo={grupo} />
          <div className="card-actions pt-1">
            {grupo === "para_decidir" ? (
              <>
                <button type="button" className="btn btn-success btn-sm" disabled={ocupado} onClick={() => onDecidir("confirmar")}>
                  C · é o mesmo
                </button>
                <button type="button" className="btn btn-error btn-outline btn-sm" disabled={ocupado} onClick={() => onDecidir("ignorar")}>
                  I · não é
                </button>
                <button type="button" className="btn btn-ghost btn-sm" disabled={ocupado} onClick={() => onDecidir("trocar")}>
                  é de outro produto…
                </button>
              </>
            ) : (
              <>
                <button type="button" className="btn btn-ghost btn-sm" disabled={ocupado} onClick={() => onDecidir("desfazer")}>
                  desfazer
                </button>
                {grupo === "confirmados" && onDefinirIdioma && (
                  <DefinirIdioma anuncio={anuncio} onDefinir={onDefinirIdioma} ocupado={ocupado} />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
