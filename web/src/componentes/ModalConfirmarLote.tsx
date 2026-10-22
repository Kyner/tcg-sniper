// Confirmação de uma ação em lote no catálogo: mostra o número exato de produtos afetados. Se a contagem mudou
// no servidor, o número novo aparece com o aviso e o usuário confirma de novo.
import { Modal } from "./Modal";

export function ModalConfirmarLote({
  acao, alvo, aviso, ocupado, aoConfirmar, aoFechar,
}: {
  acao: "ligar" | "desligar";
  alvo: number;
  aviso: string | null;
  ocupado: boolean;
  aoConfirmar: () => void;
  aoFechar: () => void;
}) {
  const verbo = acao === "ligar" ? "Ligar" : "Desligar";
  const titulo = `${verbo} ${alvo} ${alvo === 1 ? "produto" : "produtos"}?`;
  return (
    <Modal tituloId="titulo-lote" aoFechar={aoFechar}>
      <div className="modal-box">
        <h3 id="titulo-lote" className="text-lg font-bold">{titulo}</h3>
        <p className="py-3">
          {acao === "ligar"
            ? "Eles passam a ser monitorados." : "Eles deixam de ser monitorados; o histórico de preços continua guardado."}
        </p>
        {aviso && <div role="status" className="alert alert-warning"><span>{aviso}</span></div>}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar} disabled={ocupado}>Cancelar</button>
          <button type="button" className="btn btn-primary" onClick={aoConfirmar} disabled={ocupado || alvo === 0}>
            Confirmar
          </button>
        </div>
      </div>
    </Modal>
  );
}
