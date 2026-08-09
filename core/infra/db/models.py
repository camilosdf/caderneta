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
