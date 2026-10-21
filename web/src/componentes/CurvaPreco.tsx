// Curva de preço do produto: Amazon (menor elegível), Liga "a partir de", médio da Liga e preço alvo (Liga com o
// desconto mínimo), com as oportunidades como faixas. Linhas em degrau: o preço vale até a próxima leitura.
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useCoresTema } from "../cores";
import { dataHora, reais } from "../formato";
import type { Historico } from "../tipos";

const ms = (iso: string) => new Date(iso).getTime();

export function CurvaPreco({ historico, destaque }: { historico: Historico; destaque: number | null }) {
  const cores = useCoresTema();
  const fator = 1 - historico.desconto_min_pct / 100;
  const amazon = historico.amazon.map((p) => ({ t: ms(p.t), amazon: Number(p.preco), anuncio: p.anuncio }));
  const liga = historico.liga.map((p) => ({ t: ms(p.t), liga: Number(p.preco), alvo: Number(p.preco) * fator }));
  const medio = historico.liga_medio.map((p) => ({ t: ms(p.t), medio: Number(p.preco) }));
  const resumo = `Curva de preço: ${amazon.length} leituras da Amazon e ${liga.length} da Liga`;
  return (
    <figure aria-label={resumo} className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
            <CartesianGrid strokeOpacity={0.15} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => dataHora(new Date(t).toISOString())} stroke={cores.texto} fontSize={11} />
            <YAxis tickFormatter={(v: number) => reais(String(v))} stroke={cores.texto} fontSize={11} width={84} />
            <Tooltip labelFormatter={(t) => dataHora(new Date(Number(t)).toISOString())}
              formatter={(v) => reais(String(v))} />
            <Legend />
            {historico.faixas.map((f) => (
              <ReferenceArea key={f.id} x1={ms(f.inicio)} x2={ms(f.fim)} fill={cores.sucesso}
                fillOpacity={f.id === destaque ? 0.35 : 0.12} ifOverflow="extendDomain" />
            ))}
            <Line data={amazon} dataKey="amazon" name="Amazon" type="stepAfter" stroke={cores.primaria} dot={false} strokeWidth={2} />
            <Line data={liga} dataKey="liga" name="Liga (a partir de)" type="stepAfter" stroke={cores.secundaria} dot={false} />
            <Line data={medio} dataKey="medio" name="Liga (média)" type="stepAfter" stroke={cores.texto} strokeOpacity={0.5} dot={false} />
            <Line data={liga} dataKey="alvo" name="Preço alvo" type="stepAfter" stroke={cores.aviso} strokeDasharray="5 4" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="flex flex-wrap gap-x-4 text-sm opacity-70">
        {amazon.length === 0 && <span>Ainda não há leituras suficientes para a curva</span>}
        {liga.length === 0 && <span>sem preço da Liga no período</span>}
      </figcaption>
    </figure>
  );
}
