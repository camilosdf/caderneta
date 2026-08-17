"""Modelos ORM — A2.

Mapeamento SQLAlchemy 2 das entidades de domínio para tabelas relacionais.

Princípio: os modelos ORM são estruturas de persistência independentes
das entidades de domínio. A conversão entre os dois mundos é feita
pelos Repositórios (A3), não aqui.

Tabelas:
    documentos       → Documento
    lancamentos      → Lancamento
    splits           → Split (filhos de Lancamento)
    audit_eventos    → EventoAuditoria (append-only, hash chain)
    cartoes_credito  → CartaoCredito (ADR 010)
    faturas_cartao   → FaturaCartao (ADR 010, filhos de CartaoCredito)
    compras_cartao   → CompraCartao (ADR 010, filhos de FaturaCartao)
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from core.infra.db.session import Base

# JSONB no PostgreSQL, JSON no SQLite (testes)
_JSON = JSONB().with_variant(JSON(), "sqlite")


class DocumentoORM(Base):
    """Persiste Documento — um arquivo financeiro recebido para processamento."""

    __tablename__ = "documentos"

    # Identidade
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(500), nullable=False)

    # Classificação
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    fonte_extracao: Mapped[str] = mapped_column(String(30), nullable=False)

    # Emitente
    cnpj_emitente: Mapped[str | None] = mapped_column(String(14), nullable=True)
    nome_emitente: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Datas
    data_emissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_vencimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_processamento: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Valores monetários (BRL — Decimal(15,2))
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_desconto: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    valor_liquido: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Campos fiscais
    chave_acesso: Mapped[str | None] = mapped_column(String(44), nullable=True)
    numero_documento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cfop: Mapped[str | None] = mapped_column(String(10), nullable=True)
    natureza_operacao: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # MetadadosNFe serializado como JSON (estrutura rica, pouco consultada por coluna)
    metadados_nfe: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    # Qualidade e revisão
    confidence_minima: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    precisa_revisao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relacionamentos
    lancamentos: Mapped[list["LancamentoORM"]] = relationship(
        "LancamentoORM", back_populates="documento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("empresa_id", "hash_sha256", name="uq_documento_hash_empresa"),
    )

    def __repr__(self) -> str:
        return f"<DocumentoORM id={self.id} tipo={self.tipo} arquivo={self.nome_arquivo}>"


class SplitORM(Base):
    """Persiste Split — uma partida (débito/crédito) dentro de um lançamento."""

    __tablename__ = "splits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lancamento_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    conta_codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    natureza: Mapped[str] = mapped_column(String(10), nullable=False)   # debito | credito
    valor: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    moeda: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    centro_custo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    descricao: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relacionamento
    lancamento: Mapped["LancamentoORM"] = relationship("LancamentoORM", back_populates="splits")

    def __repr__(self) -> str:
        return f"<SplitORM {self.natureza} {self.conta_codigo} {self.valor}>"


class LancamentoORM(Base):
    """Persiste Lancamento — agregado raiz contábil com partidas dobradas."""

    __tablename__ = "lancamentos"

    # Identidade
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    documento_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documentos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fornecedor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Datas
    data_lancamento: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    data_competencia: Mapped[date | None] = mapped_column(Date, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Descrição
    descricao: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    historico_padronizado: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Parcelamento
    e_parcelado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parcela_atual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_parcelas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lancamento_pai_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Classificação
    categoria: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    metodo_classificacao: Mapped[str | None] = mapped_column(String(50), nullable=True)
    regra_aplicada_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    versao_regra: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Aprovação
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="rascunho", index=True)
    nivel_aprovacao: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pre_aprovado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Autoria (Gate 0 — D1). Nullable: ausência = origem desconhecida,
    # tratada como falha fechada por PolicyEngine.avaliar_aprovacao().
    criado_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aprovado_por_1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aprovado_em_1: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aprovado_por_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aprovado_em_2: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Integração externa
    guid_gnucash: Mapped[str | None] = mapped_column(String(36), nullable=True)
    exportado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relacionamentos
    documento: Mapped["DocumentoORM | None"] = relationship(
        "DocumentoORM", back_populates="lancamentos"
    )
    splits: Mapped[list["SplitORM"]] = relationship(
        "SplitORM", back_populates="lancamento", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LancamentoORM id={self.id} status={self.status} descricao={self.descricao[:30]}>"


class AuditEventoORM(Base):
    """Persiste EventoAuditoria — append-only, nunca atualizado ou deletado.

    A hash chain garante imutabilidade: qualquer alteração quebra a cadeia.
    A constraint NOT NULL em hash_proprio garante que todo evento foi assinado.
    """

    __tablename__ = "audit_eventos"

    # Identidade e hash chain
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hash_proprio: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hash_anterior: Mapped[str] = mapped_column(String(64), nullable=False)

    # Metadados do evento
    tipo: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timestamp: Mapped[str] = mapped_column(String(35), nullable=False, index=True)
    versao_sistema: Mapped[str] = mapped_column(String(20), nullable=False)

    # Contexto
    usuario: Mapped[str | None] = mapped_column(String(100), nullable=True)
    empresa_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    lancamento_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    documento_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    documento_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Auditoria de alterações
    campo_alterado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valor_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_novo: Mapped[str | None] = mapped_column(Text, nullable=True)
    versao_regra: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Payload livre
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False)

    def __repr__(self) -> str:
        return f"<AuditEventoORM tipo={self.tipo} ts={self.timestamp}>"


class PeriodoContabilORM(Base):
    """Persiste PeriodoContabil — controle de abertura/fechamento por competência."""

    __tablename__ = "periodos_contabeis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    ano: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aberto")
    fechado_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fechado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("empresa_id", "ano", "mes", name="uq_periodo_empresa_competencia"),
    )

    def __repr__(self) -> str:
        return f"<PeriodoContabilORM {self.ano}/{self.mes:02d} status={self.status}>"


class CentroCustoORM(Base):
    """Persiste CentroCusto — dimensão de rateio/análise de despesas."""

    __tablename__ = "centros_custo"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_centro_custo_empresa_codigo"),
    )

    def __repr__(self) -> str:
        return f"<CentroCustoORM {self.codigo} ativo={self.ativo}>"


class UsuarioORM(Base):
    """Persiste Usuario — identidade e papel para a Interface Web (ADR 008).

    senha_hash nunca é exposta ao domínio — Usuario (core/domain/entities.py)
    não carrega esse campo. Verificação de senha é responsabilidade de
    api/auth/security.py, nunca de core/ (ver ADR 008, matriz de importação).

    current_authentication_id: referência à sessão ativa no servidor —
    o cookie assinado carrega apenas um authentication_id (portador de
    identidade), nunca a autorização em si. A cada requisição autenticada,
    o valor do cookie é comparado contra este campo; logout zera o campo,
    invalidando imediatamente qualquer cópia antiga do cookie que ainda
    tenha assinatura válida (achado de segurança do W2 — Starlette
    SessionMiddleware sozinho é inteiramente client-side, sem isso o
    logout não revoga cópias do cookie capturadas antes dele).

    MVP: no máximo uma sessão autenticada por usuário — um novo login
    sobrescreve este campo, invalidando qualquer sessão anterior. Se
    múltiplas sessões simultâneas forem necessárias no futuro, substituir
    por uma tabela `sessoes` (id, usuario_id, authentication_id,
    created_at, expires_at, revogada) sem alterar a interface pública
    da API.
    """

    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    papel: Mapped[str] = mapped_column(String(20), nullable=False, default="operador")
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_authentication_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<UsuarioORM {self.email} papel={self.papel}>"


class TransacaoBancariaORM(Base):
    """Persiste TransacaoBancaria — movimentos bancários importados de OFX.

    Unicidade garantida por (instituicao, numero_conta, fitid) —
    chave natural de idempotência da importação OFX.
    """

    __tablename__ = "transacoes_bancarias"
    __table_args__ = (
        UniqueConstraint(
            "instituicao", "numero_conta", "fitid",
            name="uq_transacao_bancaria_fitid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    instituicao: Mapped[str] = mapped_column(String(20), nullable=False)
    agencia: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    numero_conta: Mapped[str] = mapped_column(String(50), nullable=False)
    tipo_conta: Mapped[str] = mapped_column(String(20), nullable=False, default="corrente")
    fitid: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    valor: Mapped[str] = mapped_column(String(20), nullable=False)  # Decimal como string
    natureza: Mapped[str] = mapped_column(String(10), nullable=False)
    descricao: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    referencia: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    origem: Mapped[str] = mapped_column(String(20), nullable=False, default="ofx")
    id_importacao: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<TransacaoBancariaORM {self.fitid} {self.data} {self.valor}>"


# ---------------------------------------------------------------------------
# ADR 010 — Faturas de Cartão de Crédito (Fase 0 — schema)
#
# DT-CC-01: ContaContabil não tem persistência própria no sistema (nenhuma
# tabela contas_contabeis, nenhum ContaContabilORM). CartaoCreditoORM segue
# o mesmo padrão já usado em SplitORM.conta_codigo — referência textual,
# sem FK — em vez de uma relação persistida com ContaContabil. Ver ADR 010,
# Seção "Débito técnico registrado — DT-CC-01".
# ---------------------------------------------------------------------------


class CartaoCreditoORM(Base):
    """Persiste CartaoCredito — identidade de um cartão de crédito do titular.

    Unicidade garantida por (empresa_id, emissor, final_numero, titular) —
    chave natural de idempotência (Deliberação Complementar, B1).
    """

    __tablename__ = "cartoes_credito"
    __table_args__ = (
        UniqueConstraint(
            "empresa_id", "emissor", "final_numero", "titular",
            name="uq_cartao_credito_identidade",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    emissor: Mapped[str] = mapped_column(String(50), nullable=False)
    final_numero: Mapped[str] = mapped_column(String(4), nullable=False)
    titular: Mapped[str] = mapped_column(String(200), nullable=False)

    # DT-CC-01 — referência textual, sem FK (ver nota de módulo acima)
    conta_codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    guid_gnucash: Mapped[str | None] = mapped_column(String(36), nullable=True)

    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    faturas: Mapped[list["FaturaCartaoORM"]] = relationship(
        "FaturaCartaoORM", back_populates="cartao"
    )

    def __repr__(self) -> str:
        return f"<CartaoCreditoORM {self.emissor} ****{self.final_numero}>"


class FaturaCartaoORM(Base):
    """Persiste FaturaCartao — um ciclo de faturamento de um cartão.

    Unicidade garantida por (cartao_id, periodo_referencia) — chave natural
    de idempotência ao nível de fatura (ADR 010, D13).
    """

    __tablename__ = "faturas_cartao"
    __table_args__ = (
        UniqueConstraint(
            "cartao_id", "periodo_referencia",
            name="uq_fatura_cartao_periodo",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cartao_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cartoes_credito.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documentos.id", ondelete="SET NULL"), nullable=True, index=True
    )

    periodo_referencia: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    data_fechamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_vencimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    valor_total_declarado: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # pendente | fechada | divergente — resultado da invariante de
    # fechamento definida em D5 (itens + encargos - créditos = total)
    status_fechamento: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cartao: Mapped["CartaoCreditoORM"] = relationship(
        "CartaoCreditoORM", back_populates="faturas"
    )
    itens: Mapped[list["CompraCartaoORM"]] = relationship(
        "CompraCartaoORM", back_populates="fatura", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<FaturaCartaoORM cartao_id={self.cartao_id} periodo={self.periodo_referencia}>"


class CompraCartaoORM(Base):
    """Persiste CompraCartao — um item (linha) de uma fatura de cartão.

    tipo distingue compra/juros/multa/iof/encargo/anuidade/estorno
    (ADR 010, D4/D9/D10). Unicidade por (fatura_id, posicao_linha) —
    chave natural de idempotência ao nível de item (ADR 010, D13).
    """

    __tablename__ = "compras_cartao"
    __table_args__ = (
        UniqueConstraint(
            "fatura_id", "posicao_linha",
            name="uq_compra_cartao_posicao",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    fatura_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("faturas_cartao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lancamento_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("lancamentos.id", ondelete="SET NULL"), nullable=True, index=True
    )

    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="compra")
    estabelecimento: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descricao_original: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_compra: Mapped[date | None] = mapped_column(Date, nullable=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # Metadado informativo de parcelamento (D12 — Alternativa C).
    # Não gera lançamento mensal adicional; ver core/domain/entities.py
    # Lancamento.e_parcelado/parcela_atual/total_parcelas (mesmo padrão).
    parcela_atual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_parcelas: Mapped[int | None] = mapped_column(Integer, nullable=True)

    posicao_linha: Mapped[int] = mapped_column(Integer, nullable=False)
    hash_linha: Mapped[str | None] = mapped_column(String(64), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    fatura: Mapped["FaturaCartaoORM"] = relationship(
        "FaturaCartaoORM", back_populates="itens"
    )

    def __repr__(self) -> str:
        return f"<CompraCartaoORM tipo={self.tipo} valor={self.valor}>"


# ---------------------------------------------------------------------------
# ADR 010 — Faturas de Cartão de Crédito (Fase 6 — B6-5/B6-6/B6-14)
#
# Materializa a restrição 1:1 já testada em memória (B6-4) no nível de
# banco. As três FKs são reais (fatura_cartao_id -> faturas_cartao,
# lancamento_id -> lancamentos, transacao_bancaria_id -> transacoes_bancarias)
# — só possível porque B2 (migration de transacoes_bancarias, bloqueador
# pré-existente do Gate 0) foi resolvida antes desta etapa. Nenhuma
# referência textual sem FK nesta tabela (ao contrário de DT-CC-01, que
# tratava de uma tabela ausente — aqui as três existem).
# ---------------------------------------------------------------------------


class PagamentoFaturaCartaoORM(Base):
    """Persiste o vínculo Fatura <-> Lançamento de pagamento <-> Transação
    bancária (ADR 010, B6-5/B6-6/B6-14).

    As três UNIQUE isoladas materializam, em nível de banco, as
    invariantes já comprovadas em memória por B6-4:
      - fatura_cartao_id UNIQUE -> uma fatura tem no máximo um vínculo
        (D8 — pagamento agregado único).
      - lancamento_id UNIQUE -> um lançamento de pagamento vincula a no
        máximo uma transação.
      - transacao_bancaria_id UNIQUE -> uma transação bancária liquida
        no máximo uma obrigação — fecha a lacuna documentada no ADR
        ("Nota de escopo — fronteira cross-call de B6-3"): duas
        execuções independentes de B6-3 podem calcular CONCILIADO para
        a mesma transação, mas só uma consegue persistir aqui.
    """

    __tablename__ = "pagamentos_faturas_cartao"
    __table_args__ = (
        UniqueConstraint("fatura_cartao_id", name="uq_pagamento_fatura_cartao"),
        UniqueConstraint("lancamento_id", name="uq_pagamento_lancamento"),
        UniqueConstraint("transacao_bancaria_id", name="uq_pagamento_transacao_bancaria"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    fatura_cartao_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("faturas_cartao.id", ondelete="CASCADE"), nullable=False
    )
    lancamento_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id", ondelete="CASCADE"), nullable=False
    )
    transacao_bancaria_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transacoes_bancarias.id", ondelete="CASCADE"), nullable=False
    )

    # B6-6 — método/resultado da conciliação (espelha TipoConciliacao /
    # MetodoMatching do domínio; armazenados como string, mesmo padrão
    # já usado em FaturaCartaoORM.status_fechamento).
    metodo_matching: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<PagamentoFaturaCartaoORM fatura={self.fatura_cartao_id} status={self.status}>"
