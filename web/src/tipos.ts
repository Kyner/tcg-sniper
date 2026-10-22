// Formatos que a API devolve (src/tcg_sniper/api/). Mantenha igual aos modelos Pydantic de lá.

export type Papel = "grupo" | "operador" | "admin";

export type Permissao =
  | "ver_area_negocio"
  | "ver_oportunidades"
  | "ver_area_gestao"
  | "gerir_usuarios"
  | "gerir_acessos"
  | "ver_documentacao_api"
  | "revisar_casamentos"
  | "ver_catalogo"
  | "editar_catalogo"
  | "ver_servicos"
  | "pausar_servicos"
  | "ver_logs"
  | "ver_mensagens"
  | "reenviar_mensagens"
  | "ver_configuracoes"
  | "editar_configuracoes";

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

export type Periodo = "7d" | "30d" | "90d" | "tudo";
export type Motivo =
  | "casamento_desfeito" | "sem_leitura" | "liga_desatualizada" | "oferta_sumiu" | "vendedor" | "liga_caiu"
  | "preco_subiu";

export interface ProdutoResumo { id: number; nome: string; imagem: string | null; ativo: boolean }
export interface AnuncioResumo { titulo: string; url: string; imagem: string | null }

/** GET /api/oportunidades/resumo. Dinheiro e % vêm como texto decimal ("1299.90"). */
export interface ResumoOportunidades {
  periodo: Periodo;
  numeros: {
    diferenca_bruta: string; oportunidades: number; desconto_medio: string | null;
    duracao_media_min: number | null; produtos: number;
  };
  por_dia: { dia: string; oportunidades: number }[];
}

/** GET /api/oportunidades/ativas. */
export interface AtivasOportunidades {
  ativas: {
    id: number; produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: string; preco_liga: string;
    desconto_pct: string; aberta_em: string; em_risco_desde: string | null; motivo_risco: Motivo | null;
  }[];
  ultima_aberta_em: string | null;
}

/** Item das encerradas e do histórico do produto. */
export interface OportunidadeLinha {
  id: number; produto: ProdutoResumo; aberta_em: string; fechada_em: string | null; aberta: boolean;
  duracao_min: number; alertas: number; preco_alertado: string; menor_preco: string; preco_liga: string;
  desconto_pct: string; motivo: Motivo | null;
}

/** GET /api/oportunidades/encerradas. */
export interface EncerradasOportunidades { itens: OportunidadeLinha[]; total: number; pagina: number; por_pagina: number }

/** GET /api/oportunidades/quase. */
export interface QuaseOportunidades {
  itens: {
    produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: string; preco_liga: string; desconto_pct: string;
    falta_reais: string; falta_pp: string;
  }[];
  desconto_min_pct: number;
  piso_pct: number;
}

/** GET /api/produtos/{id}/historico. */
export interface Historico {
  produto: { id: number; nome: string; edicao: string | null; imagem: string | null; url_liga: string };
  anuncio: AnuncioResumo | null;
  periodo: Periodo;
  escala: "hora" | "dia";
  amazon: { t: string; preco: string; anuncio: string }[];
  liga: { t: string; preco: string }[];
  liga_medio: { t: string; preco: string }[];
  desconto_min_pct: number;
  faixas: { id: number; inicio: string; fim: string; aberta: boolean; motivo: Motivo | null }[];
  oportunidades: OportunidadeLinha[];
  recorrencia_30d: number;
  quase_la: boolean;
}
