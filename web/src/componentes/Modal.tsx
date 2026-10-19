// Janela modal do DaisyUI sobre o <dialog> nativo: abre com showModal() (foco preso, fundo inerte) e fecha no
// Escape (onde quer que esteja o foco) ou no botão da própria tela (aoFechar). Sem showModal (ex.: jsdom nos
// testes), abre com o atributo open.
import { useEffect, useRef, type ReactNode } from "react";

export function Modal({
  tituloId,
  aoFechar,
  children,
}: {
  tituloId: string;
  aoFechar: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const fechar = useRef(aoFechar);
  useEffect(() => {
    fechar.current = aoFechar; // o aoFechar mais novo, sem refazer o ouvinte do Escape
  });

  useEffect(() => {
    const dialogo = ref.current;
    if (!dialogo || dialogo.open) return;
    try {
      dialogo.showModal();
    } catch {
      dialogo.setAttribute("open", "");
    }
  }, []);

  useEffect(() => {
    function tecla(evento: KeyboardEvent) {
      if (evento.key !== "Escape") return;
      evento.preventDefault(); // o navegador não dispara também o "cancel" do <dialog>
      fechar.current();
    }
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, []);

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-modal="true"
      aria-labelledby={tituloId}
      onCancel={(evento) => {
        evento.preventDefault(); // quem fecha é o React (o estado da tela), não o navegador
        aoFechar();
      }}
    >
      {children}
    </dialog>
  );
}
