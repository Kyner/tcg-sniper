// Foto de produto ou anúncio: miniatura carregada sob demanda; no tamanho grande, o toque abre a foto inteira.
import { useRef } from "react";

// "a" (adaptável): média no celular, grande a partir do lg.
type Tamanho = "p" | "m" | "g" | "a";

// Classes escritas por extenso (o Tailwind só gera o que aparece literal no código).
const CAIXA: Record<Tamanho, string> = {
  p: "h-10 w-10 rounded object-contain",
  m: "h-20 w-20 rounded object-contain",
  g: "h-40 w-40 rounded object-contain",
  a: "h-20 w-20 rounded object-contain lg:h-40 lg:w-40",
};
const PLACEHOLDER: Record<Tamanho, string> = {
  p: "skeleton h-10 w-10 rounded",
  m: "skeleton h-20 w-20 rounded",
  g: "skeleton h-40 w-40 rounded",
  a: "skeleton h-20 w-20 rounded lg:h-40 lg:w-40",
};

export function Foto({ src, alt, tamanho }: { src: string | null | undefined; alt: string; tamanho: Tamanho }) {
  const janela = useRef<HTMLDialogElement>(null);
  if (!src) return <div className={PLACEHOLDER[tamanho]} role="img" aria-label={`${alt} (sem foto)`} />;
  const imagem = <img src={src} alt={alt} loading="lazy" className={CAIXA[tamanho]} />;
  if (tamanho === "p" || tamanho === "m") return imagem;
  return (
    <>
      <button type="button" className="cursor-zoom-in" aria-label={`Ampliar foto: ${alt}`} onClick={() => janela.current?.showModal()}>
        {imagem}
      </button>
      <dialog ref={janela} className="modal">
        <div className="modal-box">
          <img src={src} alt={alt} className="mx-auto max-h-[80vh] w-full object-contain" />
          <div className="modal-action">
            <form method="dialog">
              <button className="btn">Fechar</button>
            </form>
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button aria-label="Fechar">fechar</button>
        </form>
      </dialog>
    </>
  );
}
