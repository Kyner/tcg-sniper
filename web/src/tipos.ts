// Formatos que a API devolve (src/tcg_sniper/api/). Mantenha igual aos modelos Pydantic de lá.

export type Papel = "grupo" | "operador" | "admin";

export type Permissao =
  | "ver_area_negocio"
  | "ver_area_gestao"
  | "gerir_usuarios"
  | "gerir_acessos"
  | "ver_documentacao_api";

/** GET /api/auth/eu e POST /api/auth/entrar. `superadmin`: o dono do sistema (só ele mexe em admins). */
export interface Eu {
  id: number;
  nome: string;
  papel: Papel;
  superadmin: boolean;
  permissoes: Permissao[];
}

/** GET /api/usuarios (o número vem sempre mascarado). O superadmin é sempre admin e ativo. */
export interface Usuario {
  id: number;
  nome: string;
  numero_mascarado: string;
  papel: Papel;
  superadmin: boolean;
  ativo: boolean;
  criado_em: string;
  sessoes_ativas: number;
}

/** GET /api/usuarios/{id}/sessoes. */
export interface SessaoAparelho {
  id: number;
  aparelho: string;
  criada_em: string;
  ultimo_uso_em: string;
  expira_em: string;
  atual: boolean;
}

/** GET/PUT /api/acessos. */
export interface GradeAcessos {
  papeis: { papel: Papel; rotulo: string; editavel: boolean }[];
  permissoes: { permissao: Permissao; rotulo: string; descricao: string; valores: Record<Papel, boolean> }[];
}
