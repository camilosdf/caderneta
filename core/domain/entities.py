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
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

UTC = timezone.utc


def _agora() -> datetime:
    """Substitui datetime.utcnow() depreciado. Retorna datetime UTC aware."""
    return datetime.now(UTC)


# =============================================================
# ENUMERAÇÕES DE DOMÍNIO
# =============================================================

class TipoDocumento(str, Enum):
    NFE_XML       = "nfe_xml"
    OFX           = "ofx"
    CSV           = "csv"
    PDF_TEXTO     = "pdf_texto"
    PDF_IMAGEM    = "pdf_imagem"
    IMAGEM        = "imagem"
    DESCONHECIDO  = "desconhecido"


class FonteExtracao(str, Enum):
    XML        = "xml"
    OFX        = "ofx"
    CSV        = "csv"
    PDF_TEXTO  = "pdf_texto"
    OCR        = "ocr"
    LLM        = "llm"
    MANUAL     = "manual"


class NaturezaLancamento(str, Enum):
    DEBITO  = "debito"
    CREDITO = "credito"


class RegimeContabil(str, Enum):
    COMPETENCIA = "competencia"
    CAIXA       = "caixa"


class StatusLancamento(str, Enum):
    RASCUNHO  = "rascunho"
    PENDENTE  = "pendente"
    APROVADO  = "aprovado"
    REJEITADO = "rejeitado"
    EXPORTADO = "exportado"


class StatusPeriodo(str, Enum):
    ABERTO  = "aberto"
    FECHADO = "fechado"


class NivelAprovacao(str, Enum):
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
        soma = sum(n * p for n, p in zip(nums, pesos))
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
    cnpj: Optional[CNPJ] = None
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
    fechado_por: Optional[str] = None
    fechado_em: Optional[datetime] = None

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
    guid_gnucash: Optional[str] = None
    permite_lancamento: bool = True
    centro_custo_obrigatorio: bool = False
    conta_pai_id: Optional[UUID] = None
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
    cnpj: Optional[CNPJ] = None
    categoria: Optional[str] = None
    conta_debito_padrao: Optional[CodigoConta] = None
    conta_credito_padrao: Optional[CodigoConta] = None
    centro_custo_padrao: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    total_lancamentos: int = 0
    ultima_ocorrencia: Optional[date] = None
    criado_em: datetime = field(default_factory=_agora)

    def registrar_ocorrencia(self, data: date) -> None:
        self.total_lancamentos += 1
        if self.ultima_ocorrencia is None or data > self.ultima_ocorrencia:
            self.ultima_ocorrencia = data


@dataclass
class Documento:
    """Documento financeiro recebido para processamento."""
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    hash_sha256: str = ""
    nome_arquivo: str = ""
    tipo: TipoDocumento = TipoDocumento.DESCONHECIDO
    fonte_extracao: FonteExtracao = FonteExtracao.MANUAL

    cnpj_emitente: Optional[CNPJ] = None
    nome_emitente: Optional[str] = None
    data_emissao: Optional[date] = None
    data_vencimento: Optional[date] = None
    valor_total: Optional[Dinheiro] = None
    valor_desconto: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    valor_liquido: Optional[Dinheiro] = None

    chave_acesso: Optional[str] = None
    numero_documento: Optional[str] = None
    cfop: Optional[str] = None
    natureza_operacao: Optional[NaturezaLancamento] = None

    confidence_scores: list[ConfidenceScore] = field(default_factory=list)
    precisa_revisao: bool = False
    motivo_revisao: Optional[str] = None

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
    categoria: Optional[str] = None
    conta_debito: Optional[CodigoConta] = None
    conta_credito: Optional[CodigoConta] = None
    centro_custo: Optional[str] = None
    prioridade: int = 100
    ativa: bool = True
    versao: int = 1
    criada_por: Optional[str] = None
    criada_em: datetime = field(default_factory=_agora)


@dataclass
class Split:
    """Uma partida (débito ou crédito) dentro de um lançamento."""
    id: UUID = field(default_factory=uuid4)
    conta: CodigoConta = field(default_factory=lambda: CodigoConta("1.1"))
    natureza: NaturezaLancamento = NaturezaLancamento.DEBITO
    valor: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    centro_custo: Optional[str] = None
    descricao: Optional[str] = None


@dataclass
class Lancamento:
    """Lançamento contábil — agregado raiz do domínio contábil.

    Invariante fundamental: soma dos débitos = soma dos créditos.
    Verificada em validar() antes de qualquer exportação.
    """
    id: UUID = field(default_factory=uuid4)
    empresa_id: UUID = field(default_factory=uuid4)
    documento_id: Optional[UUID] = None
    fornecedor_id: Optional[UUID] = None

    data_lancamento: Optional[date] = None
    data_competencia: Optional[date] = None
    descricao: str = ""
    historico_padronizado: Optional[str] = None

    splits: list[Split] = field(default_factory=list)

    e_parcelado: bool = False
    parcela_atual: Optional[int] = None
    total_parcelas: Optional[int] = None
    lancamento_pai_id: Optional[UUID] = None

    categoria: Optional[str] = None
    confidence: Optional[float] = None
    metodo_classificacao: Optional[str] = None
    regra_aplicada_id: Optional[UUID] = None
    versao_regra: Optional[int] = None

    status: StatusLancamento = StatusLancamento.RASCUNHO
    nivel_aprovacao: Optional[NivelAprovacao] = None
    pre_aprovado: bool = False
    aprovado_por_1: Optional[str] = None
    aprovado_em_1: Optional[datetime] = None
    aprovado_por_2: Optional[str] = None
    aprovado_em_2: Optional[datetime] = None

    guid_gnucash: Optional[str] = None
    exportado_em: Optional[datetime] = None

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
