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

/** GET /api/gestao/menu: o selo do menu da gestão (0 para quem não revisa casamentos). */
export interface MenuGestao {
  casamentos_esperando: number;
}

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
  | "preco_subiu" | "produto_desativado";

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
  desconto_pct: string; motivo: Motivo | null; anuncio: AnuncioResumo;
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
  sem_preco: boolean;
  anuncios_casados: number;
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

/** GET /api/gestao/casamentos: uma linha da lista. */
export interface ProdutoCasamento {
  id: number;
  nome: string;
  nome_en: string | null;
  imagem: string | null;
  categoria: string | null;
  preco_liga: string | null;
  pendentes: number;
  confirmados: number;
  ignorados: number;
  em_outro: number;
  ia_sugere: number;
  situacao: string;
}

export interface ListaCasamentos {
  itens: ProdutoCasamento[];
  total: number;
  pagina: number;
  por_pagina: number;
  categorias: string[];
}

/** GET /api/gestao/casamentos/{id}: o produto da Liga em revisão. */
export interface ProdutoLigaRevisao {
  id: number;
  nome: string;
  nome_en: string | null;
  imagem: string | null;
  categoria: string | null;
  url: string;
  preco_liga: string | null;
  lojas: number | null;
  pistas: string[];
}

/** Produto da Liga parecido (ou candidato em "é de outro produto"). */
export interface ProdutoParecido {
  id: number;
  nome: string;
  imagem: string | null;
  preco_liga: string | null;
}

export interface ParecerIa {
  mesmo_produto: boolean;
  confianca: number;
  motivo: string;
  idioma: string | null;
}

export type GrupoRevisao = "para_decidir" | "confirmados" | "ignorados";
export type AcaoCasamento = "confirmar" | "ignorar" | "desfazer" | "trocar";

/** Um anúncio da Amazon na revisão de um produto. */
export interface AnuncioRevisao {
  anuncio_id: number;
  asin: string;
  titulo: string;
  url: string;
  imagem: string | null;
  preco: string | null;
  vendedor: string | null;
  termos_variacao: string[];
  /** O idioma definido no anúncio ou, sem ele, o lido pela IA. */
  idioma: string | null;
  ia: ParecerIa | null;
  origem: string | null;
  revisado_em: string | null;
  oportunidade: boolean;
  casado_com: ProdutoParecido | null;
}

export interface NavegacaoRevisao {
  posicao: number;
  total: number;
  anterior: number | null;
  proximo: number | null;
}

export interface RevisaoCasamento {
  produto: ProdutoLigaRevisao;
  navegacao: NavegacaoRevisao;
  para_decidir: AnuncioRevisao[];
  confirmados: AnuncioRevisao[];
  ignorados: AnuncioRevisao[];
  parecidos: ProdutoParecido[];
  termos: string[];
  termos_pedidos: boolean;
}

/** POST /api/gestao/casamentos/{id}/anuncios/{anuncio}. */
export interface DecisaoCasamento {
  anuncio: AnuncioRevisao;
  grupo: GrupoRevisao;
  mensagem: string | null;
}

/** Resposta de Rebuscar, Reavaliar e Gerar termos. */
export interface MensagemAcao {
  tipo: "success" | "info" | "warning";
  mensagem: string;
}

/** GET /api/gestao/catalogo: uma linha da lista. */
export interface LinhaCatalogo {
  id: number;
  nome: string;
  nome_en: string | null;
  imagem: string | null;
  categoria: string | null;
  monitorado: boolean;
  preco_liga: string | null;
  lojas: number | null;
  situacao: string;
  pendentes: number;
  confirmados: number;
  melhor_amazon: string | null;
  medio_liga: string | null;
  /** Quanto a Amazon está abaixo da média de venda da Liga (negativo: acima). */
  diferenca_media_pct: string | null;
  /** Última coleta da listagem em que o produto teve "a partir de"; null = sem registro de preço. */
  sem_vendedor_desde: string | null;
}

export interface ListaCatalogo {
  itens: LinhaCatalogo[];
  total: number;
  pagina: number;
  por_pagina: number;
  categorias: string[];
}

/** POST /api/gestao/catalogo/lote. */
export interface LoteCatalogo { alvo: number; alterados: number }

/** GET /api/gestao/produtos/{id}: o produto na gestão. */
export interface ProdutoGestaoDados {
  produto: {
    id: number; nome: string; nome_en: string | null; imagem: string | null; categoria: string | null;
    url: string; pistas: string[];
  };
  monitorado: boolean;
  esgotado_liga: boolean;
  liga: { preco: string | null; lojas: number | null; medio: string | null; lido_em: string | null };
  melhor_amazon: { preco: string; diferenca_pct: string | null } | null;
  casamentos: { pendentes: number; confirmados: number; ignorados: number };
  anuncio: AnuncioResumo | null;
  sem_preco: boolean;
  anuncios_casados: number;
  curva: Historico | null;
}

/** Estado único de um serviço na gestão (um só vocabulário para a tela e o painel). */
export type Estado = "rodando" | "esperando" | "atrasado" | "com_problema" | "desligado";
export type AcaoServico = "ligar" | "desligar" | "rodar_agora" | "retomar";

export interface ItemCarrinho { conferencia_id: number; asin: string; produto: string; em: string | null }
export interface SubMonitor {
  monitor_ligado: boolean; checkout_ligado: boolean; checkout_parado: boolean; carrinho: ItemCarrinho[];
}

/** GET /api/gestao/servicos: cada serviço com estado, transição, ações permitidas e (monitor) a sub-linha. */
export interface ServicoGestao {
  id: string; nome: string; estado: Estado; agora: string; detalhe: string; ultimo_ok: string | null;
  ligado: boolean; transicao: { tipo: "parando" | "parado" | "iniciando"; desde: string | null } | null;
  acoes: AcaoServico[]; abrir: string | null; atividade: string; sub: SubMonitor | null;
}
export interface ListaServicos { servicos: ServicoGestao[] }
/** Resposta das ações: o texto vai para a tela como está. */
export interface ResultadoServico { codigo: string; mensagem: string }

/** GET /api/gestao/atividade: uma linha da lista única (coletas, buscas, checkouts, IA, mensagens, backups, avisos). */
export type SituacaoAtividade = "ok" | "parcial" | "falha";
export interface LinhaAtividade {
  chave: string; em: string; servico: string | null; o_que: string; situacao: SituacaoAtividade; resultado: string;
  produto_id: number | null; produto: string | null; asin: string | null; custo_usd: string | null;
  detalhe: Record<string, string | number | null>;
}
export interface PaginaAtividade { itens: LinhaAtividade[]; proximo: string | null }

/** GET /api/gestao/dashboard: cada bloco vem `null` quando a pessoa não tem a permissão dele. */
export interface PrecisaItem { texto: string; rotulo: string; destino: string }
export interface SaudeItem { id: string; nome: string; estado: Estado; resumo: string }
export interface TopOportunidade { produto_id: number; nome: string; imagem: string | null; desconto_pct: number }
export interface FunilGestao {
  liga: number; monitorados: number; esperando_decisao: number; so_ignorados: number; sem_candidato: number;
  casados_produtos: number; casados_anuncios: number; oportunidades: number;
}
export interface DashboardGestao {
  precisa: PrecisaItem[];
  saude: SaudeItem[] | null;
  oportunidades: { top: TopOportunidade[]; abertas: number; alertas_hoje: number; alertas_semana: number } | null;
  funil: FunilGestao | null;
}
