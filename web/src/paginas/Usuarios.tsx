// Gestão → Usuários: lista (número sempre mascarado), cadastro, edição (nome, papel, ativo) e sessões.
// Só o superadmin vê a opção Admin e os botões das linhas de admin; ninguém rebaixa, desativa ou encerra o
// superadmin (na linha dele, só ele mesmo edita o nome e vê as sessões). A API recusa do mesmo jeito.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { chamarApi } from "../api";
import { ROTULO_PAPEL } from "../permissoes";
import { useSessao } from "../sessao";
import type { Papel, SessaoAparelho, Usuario } from "../tipos";

function dataHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function Usuarios() {
  const { sessao, tratarErro } = useSessao();
  const eu = sessao.estado === "logado" ? sessao.eu : null;
  const souSuperadmin = eu?.superadmin === true;
  const papeis: Papel[] = souSuperadmin ? ["grupo", "operador", "admin"] : ["grupo", "operador"];
  // Editar: operador e grupo para quem tem gerir_usuarios; admins (e a própria linha do superadmin) só o superadmin.
  const podeEditar = (u: Usuario) => (u.superadmin ? u.id === eu?.id : souSuperadmin || u.papel !== "admin");
  // Sessões: as de quem pode editar e as próprias (cada um encerra as suas).
  const podeVerSessoes = (u: Usuario) => podeEditar(u) || u.id === eu?.id;
  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState<string | null>(null);
  const [editando, setEditando] = useState<Usuario | null>(null);
  const [sessoesDe, setSessoesDe] = useState<Usuario | null>(null);

  const carregar = useCallback(async () => {
    try {
      const resposta = await chamarApi<{ usuarios: Usuario[] }>("/api/usuarios");
      setUsuarios(resposta.usuarios);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function aposSalvar(texto: string) {
    setMensagem(texto);
    setErro(null);
    setEditando(null);
    await carregar();
  }

  function mostrarErro(texto: string | null) {
    setMensagem(null);
    setErro(texto);
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Usuários</h1>
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
      <NovoUsuario papeis={papeis} aoCriar={(u) => void aposSalvar(`${u.nome} cadastrado.`)} aoErro={mostrarErro} />
      {usuarios === null ? (
        <span className="loading loading-spinner" aria-label="Carregando" />
      ) : (
        <div className="overflow-x-auto rounded-box bg-base-100 shadow-sm">
          <table className="table">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Número</th>
                <th>Papel</th>
                <th>Situação</th>
                <th>Sessões</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id}>
                  <td>{u.nome}</td>
                  <td className="whitespace-nowrap">{u.numero_mascarado}</td>
                  <td className="whitespace-nowrap">
                    <span className="badge badge-ghost">{ROTULO_PAPEL[u.papel]}</span>
                    {u.superadmin && <span className="badge badge-primary badge-sm ml-1">superadmin</span>}
                  </td>
                  <td>
                    {u.ativo ? (
                      <span className="badge badge-success">Ativo</span>
                    ) : (
                      <span className="badge badge-neutral">Desativado</span>
                    )}
                  </td>
                  <td>{u.sessoes_ativas}</td>
                  <td className="whitespace-nowrap">
                    {podeEditar(u) && (
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => setEditando(u)}>
                        Editar
                      </button>
                    )}
                    {podeVerSessoes(u) && (
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSessoesDe(u)}>
                        Sessões
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editando && (
        <EditarUsuario
          usuario={editando}
          papeis={papeis}
          aoFechar={() => setEditando(null)}
          aoSalvar={() => void aposSalvar("Alterações salvas.")}
        />
      )}
      {sessoesDe && (
        <SessoesDoUsuario
          usuario={sessoesDe}
          aoFechar={() => {
            setSessoesDe(null);
            void carregar();
          }}
        />
      )}
    </section>
  );
}

function NovoUsuario({
  papeis,
  aoCriar,
  aoErro,
}: {
  papeis: Papel[];
  aoCriar: (usuario: Usuario) => void;
  aoErro: (texto: string | null) => void;
}) {
  const { tratarErro } = useSessao();
  const [nome, setNome] = useState("");
  const [numero, setNumero] = useState("");
  const [papel, setPapel] = useState<Papel>("grupo");
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    try {
      const criado = await chamarApi<Usuario>("/api/usuarios", { metodo: "POST", corpo: { nome, numero, papel } });
      setNome("");
      setNumero("");
      setPapel("grupo");
      aoCriar(criado);
    } catch (e) {
      aoErro(tratarErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="card bg-base-100 shadow-sm">
      <div className="card-body">
        <h2 className="card-title">Novo usuário</h2>
        <div className="grid gap-2 sm:grid-cols-3">
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-nome">
              Nome
            </label>
            <input
              id="novo-nome"
              className="input w-full"
              required
              maxLength={80}
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </fieldset>
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-numero">
              Número do WhatsApp
            </label>
            <input
              id="novo-numero"
              className="input w-full"
              type="tel"
              inputMode="tel"
              placeholder="(11) 9XXXX-XXXX"
              required
              maxLength={30}
              value={numero}
              onChange={(e) => setNumero(e.target.value)}
            />
          </fieldset>
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-papel">
              Papel
            </label>
            <select
              id="novo-papel"
              className="select w-full"
              value={papel}
              onChange={(e) => setPapel(e.target.value as Papel)}
            >
              {papeis.map((p) => (
                <option key={p} value={p}>
                  {ROTULO_PAPEL[p]}
                </option>
              ))}
            </select>
          </fieldset>
        </div>
        <div className="card-actions justify-end">
          <button type="submit" className="btn btn-primary" disabled={enviando}>
            Cadastrar
          </button>
        </div>
      </div>
    </form>
  );
}

function EditarUsuario({
  usuario,
  papeis,
  aoFechar,
  aoSalvar,
}: {
  usuario: Usuario;
  papeis: Papel[];
  aoFechar: () => void;
  aoSalvar: () => void;
}) {
  const { tratarErro } = useSessao();
  const [nome, setNome] = useState(usuario.nome);
  const [papel, setPapel] = useState<Papel>(usuario.papel);
  const [ativo, setAtivo] = useState(usuario.ativo);
  const [erro, setErro] = useState<string | null>(null);
  const travado = usuario.superadmin; // sempre admin e ativo: só o nome muda (só ele mesmo abre esta tela)

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    try {
      await chamarApi<Usuario>(`/api/usuarios/${usuario.id}`, { metodo: "PATCH", corpo: { nome, papel, ativo } });
      aoSalvar();
    } catch (e) {
      setErro(tratarErro(e));
    }
  }

  return (
    <div className="modal modal-open" role="dialog" aria-modal="true" aria-labelledby="titulo-editar">
      <form className="modal-box space-y-2" onSubmit={salvar}>
        <h2 id="titulo-editar" className="text-lg font-bold">
          Editar {usuario.nome}
        </h2>
        {erro && (
          <div role="alert" className="alert alert-error">
            {erro}
          </div>
        )}
        <fieldset className="fieldset">
          <label className="fieldset-legend" htmlFor="editar-nome">
            Nome
          </label>
          <input
            id="editar-nome"
            className="input w-full"
            required
            maxLength={80}
            value={nome}
            onChange={(e) => setNome(e.target.value)}
          />
        </fieldset>
        <fieldset className="fieldset">
          <label className="fieldset-legend" htmlFor="editar-papel">
            Papel
          </label>
          <select
            id="editar-papel"
            className="select w-full"
            value={papel}
            disabled={travado}
            onChange={(e) => setPapel(e.target.value as Papel)}
          >
            {papeis.map((p) => (
              <option key={p} value={p}>
                {ROTULO_PAPEL[p]}
              </option>
            ))}
          </select>
        </fieldset>
        <label className="label gap-2" htmlFor="editar-ativo">
          <input
            id="editar-ativo"
            type="checkbox"
            className="toggle toggle-success"
            checked={ativo}
            disabled={travado}
            onChange={(e) => setAtivo(e.target.checked)}
          />
          Ativo (desativar encerra as sessões na hora)
        </label>
        {travado && <p className="text-sm opacity-70">O superadmin é sempre admin e ativo.</p>}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar}>
            Cancelar
          </button>
          <button type="submit" className="btn btn-primary">
            Salvar
          </button>
        </div>
      </form>
    </div>
  );
}

function SessoesDoUsuario({ usuario, aoFechar }: { usuario: Usuario; aoFechar: () => void }) {
  const { tratarErro } = useSessao();
  const [sessoes, setSessoes] = useState<SessaoAparelho[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const resposta = await chamarApi<{ sessoes: SessaoAparelho[] }>(`/api/usuarios/${usuario.id}/sessoes`);
      setSessoes(resposta.sessoes);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [usuario.id, tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function encerrar(id: number) {
    try {
      await chamarApi(`/api/sessoes/${id}/encerrar`, { metodo: "POST" });
      await carregar();
    } catch (e) {
      setErro(tratarErro(e));
    }
  }

  return (
    <div className="modal modal-open" role="dialog" aria-modal="true" aria-labelledby="titulo-sessoes">
      <div className="modal-box space-y-2">
        <h2 id="titulo-sessoes" className="text-lg font-bold">
          Sessões de {usuario.nome}
        </h2>
        {erro && (
          <div role="alert" className="alert alert-error">
            {erro}
          </div>
        )}
        {sessoes === null ? (
          <span className="loading loading-spinner" aria-label="Carregando" />
        ) : sessoes.length === 0 ? (
          <p>Nenhuma sessão aberta.</p>
        ) : (
          <ul className="list">
            {sessoes.map((s) => (
              <li key={s.id} className="list-row items-center">
                <div className="list-col-grow">
                  <div>
                    {s.aparelho}
                    {s.atual && <span className="badge badge-info badge-sm ml-2">esta sessão</span>}
                  </div>
                  <div className="text-xs opacity-70">Último uso: {dataHora(s.ultimo_uso_em)}</div>
                </div>
                <button type="button" className="btn btn-error btn-xs" onClick={() => void encerrar(s.id)}>
                  Encerrar
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
