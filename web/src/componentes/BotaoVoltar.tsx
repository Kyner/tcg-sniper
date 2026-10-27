// "Voltar": com página anterior do próprio site volta nela (mantém filtros e página); sem ela, vai ao padrão.
import { Link, useLocation, useNavigate } from "react-router";

export function BotaoVoltar({ padrao, rotulo = "Voltar" }: { padrao: string; rotulo?: string }) {
  const navigate = useNavigate();
  const { key } = useLocation();
  if (key === "default") return <Link className="btn btn-ghost btn-sm" to={padrao}>{rotulo}</Link>;
  return <button type="button" className="btn btn-ghost btn-sm" onClick={() => void navigate(-1)}>{rotulo}</button>;
}
