"""Etapa 1 — Modelo de Domínio.

Entidades centrais do Caderneta. Sem OCR, sem IA, sem parsers.
Apenas o domínio puro: o que o sistema sabe sobre o mundo contábil.

Regras DDD aplicadas:
- Entidades têm identidade (UUID)
- Value Objects são imutáveis (frozen dataclass)
- Agregados controlam seus invariantes internos

Correções v0.3.2:
- CNPJ: algoritmo de dígitos verificadores corrigido (pesos fixos RF)
- CodigoConta: aceita nível 1 (conta raiz sintética, ex: "4" = Despesas)
- datetime.utcnow() → datetime.now(UTC) (Python 3.12+)
- Ruff: Optional[X] → X | None, nomes de variáveis ambíguos corrigidos
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

UTC = UTC


def _agora() -> datetime:
    """Substitui datetime.utcnow() depreciado. Retorna datetime UTC aware."""
    return datetime.now(UTC)


# =============================================================
# ENUMERAÇÕES DE DOMÍNIO
# =============================================================

class TipoDocumento(StrEnum):
    NFE_XML       = "nfe_xml"
    OFX           = "ofx"
    CSV           = "csv"
    PDF_TEXTO     = "pdf_texto"
    PDF_IMAGEM    = "pdf_imagem"
    IMAGEM        = "imagem"
    DESCONHECIDO  = "desconhecido"


class FonteExtracao(StrEnum):
    XML        = "xml"
    OFX        = "ofx"
    CSV        = "csv"
    PDF_TEXTO  = "pdf_texto"
    OCR        = "ocr"
    LLM        = "llm"
    MANUAL     = "manual"


class NaturezaLancamento(StrEnum):
    DEBITO  = "debito"
    CREDITO = "credito"


class RegimeContabil(StrEnum):
    COMPETENCIA = "competencia"
    CAIXA       = "caixa"


class StatusLancamento(StrEnum):
    RASCUNHO  = "rascunho"
    PENDENTE  = "pendente"
    APROVADO  = "aprovado"
    REJEITADO = "rejeitado"
    EXPORTADO = "exportado"


class StatusPeriodo(StrEnum):
    ABERTO  = "aberto"
    FECHADO = "fechado"


class NivelAprovacao(StrEnum):
    AUTOMATICO       = "automatico"
    UM_APROVADOR     = "um_aprovador"
    DOIS_APROVADORES = "dois_aprovadores"


# =============================================================
# VALUE OBJECTS
# =============================================================

@dataclass(frozen=True)
class Dinheiro:
    """Value Object imutável para valores monetários."""
    valor: Decimal
    moeda: str = "BRL"

    def __post_init__(self) -> None:
        if self.valor < 0:
            raise ValueError(f"Dinheiro não pode ser negativo: {self.valor}")

    def __add__(self, other: "Dinheiro") -> "Dinheiro":
        if self.moeda != other.moeda:
            raise ValueError(f"Moedas incompatíveis: {self.moeda} e {other.moeda}")
        return Dinheiro(self.valor + other.valor, self.moeda)

    def __str__(self) -> str:
        return f"{self.moeda} {self.valor:,.2f}"


@dataclass(frozen=True)
class CNPJ:
    """Value Object para CNPJ validado.

    Algoritmo: dígitos verificadores conforme Receita Federal do Brasil.
    Pesos do primeiro dígito:  [5,4,3,2,9,8,7,6,5,4,3,2]
    Pesos do segundo dígito:   [6,5,4,3,2,9,8,7,6,5,4,3,2]
    """
    numero: str  # apenas dígitos, 14 chars

    # Pesos fixos conforme algoritmo da Receita Federal
    _PESOS_D1: tuple[int, ...] = field(
        default=(5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        init=False, repr=False, compare=False,
    )
    _PESOS_D2: tuple[int, ...] = field(
        default=(6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        init=False, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        limpo = "".join(c for c in self.numero if c.isdigit())
        if len(limpo) != 14:
            raise ValueError(
                f"CNPJ deve ter 14 dígitos numéricos, "
                f"recebido '{self.numero}' ({len(limpo)} dígitos)"
            )
        if not self._validar(limpo):
            raise ValueError(f"CNPJ com dígitos verificadores inválidos: {self.numero}")
        object.__setattr__(self, "numero", limpo)

    @staticmethod
    def _calc_digito(nums: list[int], pesos: tuple[int, ...]) -> int:
        soma = sum(n * p for n, p in zip(nums, pesos, strict=False))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    def _validar(self, cnpj: str) -> bool:
        # CNPJs com todos os dígitos iguais são inválidos (ex: 00000000000000)
        if len(set(cnpj)) == 1:
            return False
        nums = [int(c) for c in cnpj]
        d1 = self._calc_digito(nums[:12], self._PESOS_D1)
        d2 = self._calc_digito(nums[:12] + [d1], self._PESOS_D2)
        return nums[12] == d1 and nums[13] == d2

    def formatado(self) -> str:
        n = self.numero
        return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


@dataclass(frozen=True)
class CodigoConta:
    """Value Object para código de conta contábil.

    Estrutura do plano de contas brasileiro:
      Nível 1 — Grupo raiz:       "4"           (sintética)
      Nível 2 — Subgrupo:         "4.1"         (sintética)
      Nível 3 — Conta grupo:      "4.1.01"      (sintética)
      Nível 4 — Conta analítica:  "4.1.01.001"  (permite lançamentos)
      Nível 5 — Subconta:         "4.1.01.001.01" (permite lançamentos)

    Contas dos níveis 1-3 são sintéticas (agrupadores).
    Contas dos níveis 4-5 são analíticas (recebem lançamentos diretos).
    """
    codigo: str

    def __post_init__(self) -> None:
        if not self.codigo or not self.codigo.strip():
            raise ValueError("Código de conta não pode ser vazio.")
        partes = self.codigo.split(".")
        if not (1 <= len(partes) <= 5):
            raise ValueError(
                f"Código de conta inválido: '{self.codigo}'. "
                f"Esperado entre 1 e 5 níveis separados por ponto."
            )
        # Cada parte deve conter apenas dígitos
        for parte in partes:
            if not parte.isdigit():
                raise ValueError(
                    f"Código de conta inválido: '{self.codigo}'. "
                    f"Parte '{parte}' contém caracteres não numéricos."
                )

    @property
    def nivel(self) -> int:
        return len(self.codigo.split("."))

    @property
    def e_sintetica(self) -> bool:
        """Contas sintéticas (níveis 1-3) não recebem lançamentos diretos."""
        return self.nivel < 4

    def validar_para_lancamento(self) -> None:
        """Lança ValueError se a conta não aceita lançamentos diretos."""
        if self.e_sintetica:
            raise ValueError(
                f"Conta sintética não aceita lançamentos diretos: '{self.codigo}'. "
                f"Use uma conta analítica (nível 4 ou 5)."
            )


@dataclass(frozen=True)
class ConfidenceScore:
    """Value Object para score de confiança de extração/classificação."""
    valor: float
    campo: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.valor <= 1.0):
            raise ValueError(
                f"Score deve estar entre 0.0 e 1.0, recebido: {self.valor}"
            )

    @property
    def e_confiavel(self) -> bool:
        return self.valor >= 0.90

    @property
    def e_pre_aprovavel(self) -> bool:
        return self.valor >= 0.99


# =============================================================
# ENTIDADES
# =============================================================

@dataclass
class Empresa:
    """Empresa dona do livro contábil."""
    id: UUID = field(default_factory=uuid4)
    cnpj: CNPJ | None = None
    nome: str = ""
    regime: RegimeContabil = RegimeContabil.COMPETENCIA
    moeda: str = "BRL"
    criada_em: datetime = field(default_factory=_agora)


@dataclass
class PeriodoContabil:
    """Período contábil com controle de abertura e fechamento."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    ano: int = 0
    mes: int = 0
    status: StatusPeriodo = StatusPeriodo.ABERTO
    fechado_por: str | None = None
    fechado_em: datetime | None = None

    def fechar(self, responsavel: str) -> None:
        if self.status == StatusPeriodo.FECHADO:
            raise ValueError(f"Período {self.ano}/{self.mes:02d} já está fechado.")
        self.status = StatusPeriodo.FECHADO
        self.fechado_por = responsavel
        self.fechado_em = _agora()

    def verificar_aberto(self) -> None:
        if self.status == StatusPeriodo.FECHADO:
            raise ValueError(
                f"Período {self.ano}/{self.mes:02d} está fechado. "
                f"Reabrir requer autorização do Supervisor."
            )


@dataclass
class CentroCusto:
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    codigo: str = ""
    nome: str = ""
    ativo: bool = True


@dataclass
class ContaContabil:
    """Conta do Plano de Contas."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    codigo: CodigoConta = field(default_factory=lambda: CodigoConta("1.1"))
    nome: str = ""
    tipo: str = ""
    natureza: NaturezaLancamento = NaturezaLancamento.DEBITO
    guid_gnucash: str | None = None
    permite_lancamento: bool = True
    centro_custo_obrigatorio: bool = False
    conta_pai_id: UUID | None = None
    versao: int = 1

    def validar_para_lancamento(self) -> None:
        self.codigo.validar_para_lancamento()
        if not self.permite_lancamento:
            raise ValueError(
                f"Conta configurada como não lançável: {self.codigo.codigo}"
            )


@dataclass
class Fornecedor:
    """Fornecedor ou contraparte de um documento financeiro."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    nome_canonico: str = ""
    cnpj: CNPJ | None = None
    categoria: str | None = None
    conta_debito_padrao: CodigoConta | None = None
    conta_credito_padrao: CodigoConta | None = None
    centro_custo_padrao: str | None = None
    aliases: list[str] = field(default_factory=list)
    total_lancamentos: int = 0
    ultima_ocorrencia: date | None = None
    criado_em: datetime = field(default_factory=_agora)

    def registrar_ocorrencia(self, data: date) -> None:
        self.total_lancamentos += 1
        if self.ultima_ocorrencia is None or data > self.ultima_ocorrencia:
            self.ultima_ocorrencia = data


@dataclass(frozen=True)
class MetadadosNFe:
    """Value Object com campos fiscais específicos de NF-e.

    Separado de Documento para não inflar a entidade central com
    campos irrelevantes para OFX/CSV/PDF.
    """
    chave_acesso: str                          # 44 dígitos — unicidade e auditoria
    finalidade: int                            # 1=normal 2=complementar 3=ajuste 4=devolução
    natureza_operacao_texto: str               # <natOp> — texto livre
    cfop_itens: tuple[str, ...]                # CFOPs de todos os itens
    ncm_itens: tuple[str, ...]                 # NCMs de todos os itens
    cst_icms: str | None                    # CST ou CSOSN predominante
    cnpj_destinatario: CNPJ | None
    valor_icms: Dinheiro
    valor_pis: Dinheiro
    valor_cofins: Dinheiro
    valor_ipi: Dinheiro

    @property
    def e_devolucao(self) -> bool:
        return self.finalidade == 4

    @property
    def e_complementar(self) -> bool:
        return self.finalidade == 2

    @property
    def cfop_predominante(self) -> str | None:
        """CFOP mais frequente nos itens."""
        if not self.cfop_itens:
            return None
        return max(set(self.cfop_itens), key=self.cfop_itens.count)

    @property
    def total_tributos(self) -> Dinheiro:
        return self.valor_icms + self.valor_pis + self.valor_cofins + self.valor_ipi


@dataclass
class Documento:
    """Documento financeiro recebido para processamento."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    hash_sha256: str = ""
    nome_arquivo: str = ""
    tipo: TipoDocumento = TipoDocumento.DESCONHECIDO
    fonte_extracao: FonteExtracao = FonteExtracao.MANUAL

    cnpj_emitente: CNPJ | None = None
    nome_emitente: str | None = None
    data_emissao: date | None = None
    data_vencimento: date | None = None
    valor_total: Dinheiro | None = None
    valor_desconto: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    valor_liquido: Dinheiro | None = None

    chave_acesso: str | None = None
    numero_documento: str | None = None
    cfop: str | None = None
    natureza_operacao: NaturezaLancamento | None = None

    metadados_nfe: MetadadosNFe | None = None

    confidence_scores: list[ConfidenceScore] = field(default_factory=list)
    precisa_revisao: bool = False
    motivo_revisao: str | None = None

    data_processamento: datetime = field(default_factory=_agora)

    @property
    def confidence_minima(self) -> float:
        if not self.confidence_scores:
            return 1.0
        return min(s.valor for s in self.confidence_scores)

    def marcar_revisao(self, motivo: str) -> None:
        self.precisa_revisao = True
        self.motivo_revisao = motivo


@dataclass
class RegraClassificacao:
    """Regra de classificação contábil — compatibilidade com parsers v0.1."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    nome: str = ""
    condicao: dict = field(default_factory=dict)
    categoria: str | None = None
    conta_debito: CodigoConta | None = None
    conta_credito: CodigoConta | None = None
    centro_custo: str | None = None
    prioridade: int = 100
    ativa: bool = True
    versao: int = 1
    criada_por: str | None = None
    criada_em: datetime = field(default_factory=_agora)


@dataclass
class Split:
    """Uma partida (débito ou crédito) dentro de um lançamento."""
    id: UUID = field(default_factory=uuid4)
    conta: CodigoConta = field(default_factory=lambda: CodigoConta("1.1"))
    natureza: NaturezaLancamento = NaturezaLancamento.DEBITO
    valor: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    centro_custo: str | None = None
    descricao: str | None = None


@dataclass
class Lancamento:
    """Lançamento contábil — agregado raiz do domínio contábil.

    Invariante fundamental: soma dos débitos = soma dos créditos.
    Verificada em validar() antes de qualquer exportação.
    """
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    documento_id: UUID | None = None
    fornecedor_id: UUID | None = None

    data_lancamento: date | None = None
    data_competencia: date | None = None
    descricao: str = ""
    historico_padronizado: str | None = None

    splits: list[Split] = field(default_factory=list)

    e_parcelado: bool = False
    parcela_atual: int | None = None
    total_parcelas: int | None = None
    lancamento_pai_id: UUID | None = None

    categoria: str | None = None
    confidence: float | None = None
    metodo_classificacao: str | None = None
    regra_aplicada_id: UUID | None = None
    versao_regra: int | None = None

    status: StatusLancamento = StatusLancamento.RASCUNHO
    nivel_aprovacao: NivelAprovacao | None = None
    pre_aprovado: bool = False
    aprovado_por_1: str | None = None
    aprovado_em_1: datetime | None = None
    aprovado_por_2: str | None = None
    aprovado_em_2: datetime | None = None

    guid_gnucash: str | None = None
    exportado_em: datetime | None = None

    criado_em: datetime = field(default_factory=_agora)

    def validar(self) -> None:
        """Verifica a invariante de partidas dobradas."""
        if not self.splits:
            raise ValueError("Lançamento sem splits.")

        total_debitos = sum(
            s.valor.valor for s in self.splits
            if s.natureza == NaturezaLancamento.DEBITO
        )
        total_creditos = sum(
            s.valor.valor for s in self.splits
            if s.natureza == NaturezaLancamento.CREDITO
        )

        if abs(total_debitos - total_creditos) > Decimal("0.02"):
            raise ValueError(
                f"Partidas desequilibradas: "
                f"débitos={total_debitos:.2f}, créditos={total_creditos:.2f}"
            )

    def aprovar(self, aprovador: str, nivel: int = 1) -> None:
        if nivel == 1:
            self.aprovado_por_1 = aprovador
            self.aprovado_em_1 = _agora()
            if self.nivel_aprovacao == NivelAprovacao.UM_APROVADOR:
                self.status = StatusLancamento.APROVADO
        elif nivel == 2:
            if not self.aprovado_por_1:
                raise ValueError("Aprovação de nível 1 não realizada.")
            self.aprovado_por_2 = aprovador
            self.aprovado_em_2 = _agora()
            self.status = StatusLancamento.APROVADO

    @property
    def valor_total(self) -> Dinheiro:
        total = sum(
            s.valor.valor for s in self.splits
            if s.natureza == NaturezaLancamento.DEBITO
        )
        moeda = self.splits[0].valor.moeda if self.splits else "BRL"
        return Dinheiro(total, moeda)

    @property
    def precisa_revisao(self) -> bool:
        return (
            self.confidence is not None and self.confidence < 0.90
        ) or not self.pre_aprovado


@dataclass
class Usuario:
    """Usuário do sistema com papel e permissões."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    email: str = ""
    nome: str = ""
    papel: str = "operador"
    ativo: bool = True
    criado_em: datetime = field(default_factory=_agora)

    def pode_aprovar(self) -> bool:
        return self.papel in ("contador", "supervisor", "admin")

    def pode_aprovar_alto_valor(self) -> bool:
        return self.papel in ("supervisor", "admin")

    def pode_fechar_periodo(self) -> bool:
        return self.papel in ("supervisor", "admin")


# Alias de compatibilidade com parsers herdados da v0.1
DocumentoFinanceiro = Documento


# =============================================================
# ETAPA 8 — MOTOR DE CONCILIAÇÃO BANCÁRIA
# =============================================================

class OrigemExtrato(StrEnum):
    """Origem do extrato bancário importado."""
    OFX          = "ofx"
    OPEN_FINANCE = "open_finance"
    MANUAL       = "manual"


class TipoConciliacao(StrEnum):
    """Status de conciliação de um item do relatório."""
    CONCILIADO    = "conciliado"
    DIVERGENTE    = "divergente"
    AMBIGUO       = "ambiguo"
    PENDENTE      = "pendente"
    SEM_DOCUMENTO = "sem_documento"
    DUPLICADO     = "duplicado"


class MetodoMatching(StrEnum):
    """Método pelo qual o matching foi determinado."""
    FITID              = "fitid"
    VALOR_DATA         = "valor_data"
    VALOR_DATA_DESCRICAO = "valor_data_descricao"
    SEM_MATCH          = "sem_match"


@dataclass
class ContaBancaria:
    """Identifica uma conta bancária — escopo do FITID.

    O FITID é único dentro de (instituição, conta), não globalmente.
    Portanto ContaBancaria é parte da identidade de TransacaoBancaria.
    """
    instituicao: str          # ex: "341" (Itaú), "033" (Santander)
    agencia: str = ""
    numero_conta: str = ""
    tipo_conta: str = ""      # "corrente", "poupanca", etc.

    def __str__(self) -> str:
        return f"{self.instituicao}/{self.agencia}/{self.numero_conta}"


@dataclass
class TransacaoBancaria:
    """Movimento bancário proveniente de extrato OFX ou Open Finance.

    Identidade natural: (conta_bancaria, fitid) — imutável após importação.
    Um mesmo FITID para a mesma conta nunca deve gerar dois registros
    (idempotência da importação, critério de aceite 8.1).

    Não herda de Documento nem de Lancamento — é uma entidade de domínio
    própria, representando a "visão do banco" de um movimento financeiro.
    """
    empresa_id: UUID
    conta_bancaria: ContaBancaria
    fitid: str                        # identificador único do banco (FITID/OFX)
    data: date
    valor: Dinheiro                   # sempre positivo; natureza indica direção
    natureza: NaturezaLancamento      # DEBITO ou CREDITO (do ponto de vista da conta)
    descricao: str = ""               # memo/payee do OFX, já limpo
    referencia: str = ""              # campo adicional do OFX (checknum, etc.)
    origem: OrigemExtrato = OrigemExtrato.OFX
    id_importacao: str = ""           # UUID da importação que criou este registro
    id: UUID = field(default_factory=uuid4)
    criado_em: datetime = field(default_factory=_agora)

    def chave_idempotencia(self) -> str:
        """Chave de idempotência: (instituição, conta, FITID).
        Dois registros com a mesma chave são duplicatas da mesma transação."""
        return f"{self.conta_bancaria.instituicao}:{self.conta_bancaria.numero_conta}:{self.fitid}"


@dataclass
class CandidatoMatch:
    """Um candidato de match encontrado pelo motor de conciliação.

    O motor produz candidatos antes de decidir — isso permite distinguir
    'sem candidato' (SEM_MATCH) de 'mais de um candidato' (AMBIGUO).
    """
    lancamento_id: UUID
    metodo: MetodoMatching
    score: float                          # 0.0 a 1.0
    diferenca_valor: Decimal = Decimal("0")
    diferenca_dias: int = 0
    evidencias: list[str] = field(default_factory=list)


@dataclass
class ConciliacaoItem:
    """Resultado da conciliação de uma transação bancária ou lançamento.

    Separação explícita (conforme parecer):
      - metodo/score: como o match foi determinado
      - status: resultado da conciliação após aplicar tolerâncias e unicidade

    Tanto lancamento_id quanto transacao_bancaria_id podem ser None:
      - lancamento_id=None + status=SEM_DOCUMENTO: movimento bancário sem lançamento
      - transacao_bancaria_id=None + status=PENDENTE: lançamento sem cobertura bancária
    """
    id: UUID = field(default_factory=uuid4)
    lancamento_id: UUID | None = None
    transacao_bancaria_id: UUID | None = None
    status: TipoConciliacao = TipoConciliacao.PENDENTE
    metodo: MetodoMatching = MetodoMatching.SEM_MATCH
    score: float = 0.0
    diferenca_valor: Decimal = Decimal("0")
    diferenca_dias: int = 0
    candidatos: list[CandidatoMatch] = field(default_factory=list)
    justificativa: str = ""


@dataclass
class RelatorioConciliacao:
    """Resultado completo de uma execução do motor de conciliação.

    Agrupa os itens por status para facilitar a geração de relatórios
    e a identificação de pendências. Cada item é rastreável ao FITID
    original e ao método de matching aplicado.
    """
    empresa_id: UUID
    periodo_inicio: date
    periodo_fim: date
    itens: list[ConciliacaoItem] = field(default_factory=list)
    executado_em: datetime = field(default_factory=_agora)

    @property
    def conciliados(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.CONCILIADO]

    @property
    def divergentes(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.DIVERGENTE]

    @property
    def ambiguos(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.AMBIGUO]

    @property
    def pendentes(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.PENDENTE]

    @property
    def sem_documento(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.SEM_DOCUMENTO]

    @property
    def duplicados(self) -> list[ConciliacaoItem]:
        return [i for i in self.itens if i.status == TipoConciliacao.DUPLICADO]

    @property
    def total_itens(self) -> int:
        return len(self.itens)

    @property
    def percentual_conciliado(self) -> float:
        if not self.itens:
            return 0.0
        return round(len(self.conciliados) / len(self.itens) * 100, 2)


# =============================================================
# ADR 010 — CARTÃO DE CRÉDITO
#
# DT-CC-01: CartaoCredito.conta_codigo é referência textual a uma
# conta de Passivo (CodigoConta), não uma relação persistida com
# ContaContabil — que não tem tabela própria no sistema (ver ADR 010,
# Seção "Débito técnico registrado — DT-CC-01"). Mesmo padrão já
# usado em Split.conta.
# =============================================================

class TipoItemFatura(StrEnum):
    """Tipo de item extraído de uma fatura de cartão (ADR 010, D4/D9/D10)."""
    COMPRA   = "compra"
    JUROS    = "juros"
    MULTA    = "multa"
    IOF      = "iof"
    ENCARGO  = "encargo"
    ANUIDADE = "anuidade"
    ESTORNO  = "estorno"


class StatusFechamentoFatura(StrEnum):
    """Resultado da invariante de fechamento de uma fatura (ADR 010, D5)."""
    PENDENTE   = "pendente"
    FECHADA    = "fechada"
    DIVERGENTE = "divergente"


@dataclass
class CartaoCredito:
    """Identidade de um cartão de crédito do titular (ADR 010, D2).

    Identidade natural, usada para idempotência da criação (Deliberação
    Complementar — Gate de Implementação, B1):
        (empresa_id, emissor, final_numero, titular)

    final_numero armazena apenas os últimos 4 dígitos — o número
    completo do cartão nunca deve ser persistido (Seção 24/CLAUDE.md).
    """
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    emissor: str = ""
    final_numero: str = ""
    titular: str = ""
    conta_codigo: CodigoConta = field(default_factory=lambda: CodigoConta("2.1"))
    guid_gnucash: str | None = None
    ativo: bool = True
    criado_em: datetime = field(default_factory=_agora)

    def __post_init__(self) -> None:
        if len(self.final_numero) != 4 or not self.final_numero.isdigit():
            raise ValueError(
                f"final_numero deve conter exatamente 4 dígitos "
                f"(nunca o número completo do cartão), "
                f"recebido: '{self.final_numero}'"
            )

    def chave_idempotencia(self) -> str:
        """Chave de identidade natural (Deliberação Complementar, B1)."""
        return f"{self.empresa_id}:{self.emissor}:{self.final_numero}:{self.titular}"


@dataclass
class CompraCartao:
    """Um item (linha) de uma fatura de cartão (ADR 010, D4).

    tipo distingue compra de encargos financeiros (juros/multa/IOF/
    encargo — D9/D10) e de anuidade/estorno. O metadado de parcelamento
    é puramente informativo (D12, Alternativa C) — nunca gera lançamento
    mensal adicional; o valor lançado é sempre o total da compra.
    """
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    fatura_id: UUID | None = None
    lancamento_id: UUID | None = None

    tipo: TipoItemFatura = TipoItemFatura.COMPRA
    estabelecimento: str | None = None
    descricao_original: str | None = None
    data_compra: date | None = None
    valor: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))

    # Metadado informativo apenas (D12) — não gera lançamento por parcela.
    parcela_atual: int | None = None
    total_parcelas: int | None = None

    posicao_linha: int = 0
    hash_linha: str | None = None

    confidence: ConfidenceScore | None = None
    criado_em: datetime = field(default_factory=_agora)

    @property
    def e_estorno(self) -> bool:
        """Estornos/créditos reduzem o total da fatura (D11)."""
        return self.tipo == TipoItemFatura.ESTORNO


@dataclass
class FaturaCartao:
    """Agregado raiz de um ciclo de faturamento de um cartão (ADR 010, D3).

    Invariante de fechamento (D5, corrigida — ver ADR 010):
        itens + encargos - créditos/estornos = total declarado
    Tolerância agregada de R$0,05 (Deliberação Complementar, B2).

    Divergência acima da tolerância NÃO levanta exceção — marca a
    fatura como DIVERGENTE para revisão humana, seguindo o princípio
    de regra determinística com fallback de revisão, não bloqueio
    duro (Seção 12/CLAUDE.md). Fatura sem nenhum item é erro de uso
    (não é um caso de divergência a revisar, é um agregado incompleto).
    """
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    cartao_id: UUID | None = None
    documento_id: UUID | None = None

    periodo_referencia: date | None = None
    data_fechamento: date | None = None
    data_vencimento: date | None = None
    valor_total_declarado: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))

    itens: list[CompraCartao] = field(default_factory=list)
    status_fechamento: StatusFechamentoFatura = StatusFechamentoFatura.PENDENTE

    criado_em: datetime = field(default_factory=_agora)

    _TOLERANCIA_FECHAMENTO: Decimal = field(
        default=Decimal("0.05"), init=False, repr=False, compare=False
    )

    def chave_idempotencia(self) -> str:
        """Chave de identidade natural (ADR 010, D13): (cartão, período)."""
        return f"{self.cartao_id}:{self.periodo_referencia}"

    def validar_fechamento(self) -> None:
        """Verifica a invariante de fechamento (D5) e atualiza status_fechamento.

        Não bloqueia em caso de divergência — apenas classifica. A decisão
        de impedir a geração de lançamentos a partir de uma fatura
        DIVERGENTE é responsabilidade da camada de aplicação, não desta
        entidade.
        """
        if not self.itens:
            raise ValueError("Fatura sem itens não pode ser fechada.")

        soma_creditos = sum(
            (item.valor.valor for item in self.itens if item.e_estorno),
            Decimal("0"),
        )
        soma_demais = sum(
            (item.valor.valor for item in self.itens if not item.e_estorno),
            Decimal("0"),
        )
        total_calculado = soma_demais - soma_creditos
        diferenca = abs(total_calculado - self.valor_total_declarado.valor)

        if diferenca <= self._TOLERANCIA_FECHAMENTO:
            self.status_fechamento = StatusFechamentoFatura.FECHADA
        else:
            self.status_fechamento = StatusFechamentoFatura.DIVERGENTE
