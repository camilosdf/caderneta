"""Catálogo de eventos tipados do sistema — ADR 005.

Eventos são imutáveis e versionados.
Toda comunicação entre módulos passa por aqui.
A IA escuta eventos — nunca os produz no fluxo principal.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class BaseEvento:
    """Todos os eventos herdam daqui."""
    id: str = field(default_factory=_id)
    timestamp: str = field(default_factory=_ts)
    versao_schema: int = 1
    correlacao_id: str = field(default_factory=_id)


# =============================================================
# CICLO DE VIDA DO DOCUMENTO
# =============================================================

@dataclass(frozen=True)
class DocumentoRecebido(BaseEvento):
    nome_arquivo: str = ""
    hash_sha256: str = ""
    tipo_documento: str = ""
    usuario: str = ""


@dataclass(frozen=True)
class DocumentoValidado(BaseEvento):
    documento_id: str = ""
    hash_sha256: str = ""
    tipo_documento: str = ""


@dataclass(frozen=True)
class DocumentoParseado(BaseEvento):
    documento_id: str = ""
    hash_sha256: str = ""
    fonte_extracao: str = ""
    confidence_minima: float = 0.0
    precisa_revisao: bool = False


@dataclass(frozen=True)
class DocumentoDuplicado(BaseEvento):
    hash_sha256: str = ""
    primeiro_processamento: str = ""   # timestamp do primeiro


@dataclass(frozen=True)
class DocumentoErro(BaseEvento):
    nome_arquivo: str = ""
    hash_sha256: str = ""
    erro: str = ""
    motor: str = ""   # qual motor falhou


# =============================================================
# CICLO DE VIDA DO LANÇAMENTO
# =============================================================

@dataclass(frozen=True)
class FornecedorNormalizado(BaseEvento):
    documento_id: str = ""
    nome_raw: str = ""
    nome_canonico: str = ""
    fornecedor_id: Optional[str] = None
    confidence: float = 0.0
    metodo: str = ""
    precisa_revisao: bool = False


@dataclass(frozen=True)
class ClassificacaoConcluida(BaseEvento):
    documento_id: str = ""
    categoria: str = ""
    conta_debito: str = ""
    conta_credito: str = ""
    confidence: float = 0.0
    metodo: str = ""
    regra_id: Optional[str] = None
    versao_regra: Optional[int] = None


@dataclass(frozen=True)
class LancamentoCriado(BaseEvento):
    lancamento_id: str = ""
    documento_id: str = ""
    valor: str = ""   # string para evitar problemas de serialização de Decimal
    conta_debito: str = ""
    conta_credito: str = ""
    nivel_aprovacao: str = ""
    pre_aprovado: bool = False


@dataclass(frozen=True)
class LancamentoAprovado(BaseEvento):
    lancamento_id: str = ""
    aprovado_por: str = ""
    nivel: int = 1


@dataclass(frozen=True)
class LancamentoRejeitado(BaseEvento):
    lancamento_id: str = ""
    rejeitado_por: str = ""
    motivo: str = ""


@dataclass(frozen=True)
class LancamentoEstornado(BaseEvento):
    lancamento_original_id: str = ""
    lancamento_estorno_id: str = ""
    motivo: str = ""
    responsavel: str = ""


@dataclass(frozen=True)
class DocumentoExportado(BaseEvento):
    lancamento_id: str = ""
    adaptador: str = ""   # "gnucash", "erp_next", "csv"
    guid_externo: Optional[str] = None


# =============================================================
# GOVERNANÇA
# =============================================================

@dataclass(frozen=True)
class RegraAlterada(BaseEvento):
    regra_id: str = ""
    versao_anterior: int = 0
    versao_nova: int = 0
    alterado_por: str = ""
    motivo: str = ""


@dataclass(frozen=True)
class PoliticaAlterada(BaseEvento):
    politica_id: str = ""
    versao_anterior: int = 0
    versao_nova: int = 0
    alterado_por: str = ""


@dataclass(frozen=True)
class PeriodoFechado(BaseEvento):
    ano: int = 0
    mes: int = 0
    fechado_por: str = ""


@dataclass(frozen=True)
class FeedbackRegistrado(BaseEvento):
    """Apenas ai/ escuta este evento — alimenta a Finance Knowledge Base."""
    lancamento_id: str = ""
    campo_corrigido: str = ""
    valor_original: str = ""
    valor_correto: str = ""
    usuario: str = ""


# =============================================================
# ADR 010 — FATURAS DE CARTÃO DE CRÉDITO (Fase 4)
# =============================================================

@dataclass(frozen=True)
class FaturaCartaoRecebida(BaseEvento):
    """Fatura de cartão extraída com sucesso (Fase 2) e persistida
    (D13) — paralelo a DocumentoParseado, mas específico do agregado
    FaturaCartao (D1/D3)."""
    documento_id: str = ""
    fatura_id: str = ""
    cartao_id: str = ""
    hash_sha256: str = ""
    tipo_documento: str = ""
    periodo_referencia: str = ""
    valor_total_declarado: str = ""
    n_itens: int = 0
    n_itens_baixa_confianca: int = 0


@dataclass(frozen=True)
class FaturaCartaoFechada(BaseEvento):
    """FaturaCartao.validar_fechamento() resultou em FECHADA (D5) —
    fatura pronta para gerar lançamentos (D7/D8). Renomeado do esboço
    original 'FaturaCartaoClassificada' — não há passo de classificação
    (ClassificationPort) no pipeline de fatura; o conceito real é o
    fechamento validado (ver ADR 010, fechamento de B5)."""
    fatura_id: str = ""
    status_fechamento: str = ""
    valor_total_declarado: str = ""
    soma_itens_calculada: str = ""


@dataclass(frozen=True)
class PagamentoCartaoIdentificado(BaseEvento):
    """Motor de conciliação casou uma TransacaoBancaria ao Lancamento
    de pagamento de uma fatura (D8). Catalogado nesta fase — disparo
    fica para a Fase de conciliação (fora do escopo desta etapa)."""
    fatura_id: str = ""
    lancamento_pagamento_id: str = ""
    transacao_bancaria_id: str = ""
    metodo_matching: str = ""


# =============================================================
# PORT DE BARRAMENTO DE EVENTOS (injetado via DI)
# =============================================================

from typing import Callable, Protocol, Type, TypeVar

E = TypeVar("E", bound=BaseEvento)


class EventBusPort(Protocol):
    """Contrato para qualquer implementação de barramento de eventos."""

    def publicar(self, evento: BaseEvento) -> None:
        """Publica um evento no barramento."""
        ...

    def escutar(
        self,
        tipo_evento: Type[E],
        handler: Callable[[E], None],
    ) -> None:
        """Registra um handler para um tipo de evento."""
        ...


class EventBusEmMemoria:
    """Implementação em memória para testes — sem Redis necessário."""

    def __init__(self):
        self._handlers: dict[type, list[Callable]] = {}
        self._publicados: list[BaseEvento] = []

    def publicar(self, evento: BaseEvento) -> None:
        self._publicados.append(evento)
        handlers = self._handlers.get(type(evento), [])
        for handler in handlers:
            handler(evento)

    def escutar(self, tipo_evento: type, handler: Callable) -> None:
        self._handlers.setdefault(tipo_evento, []).append(handler)

    @property
    def eventos(self) -> list[BaseEvento]:
        return list(self._publicados)

    def limpar(self) -> None:
        self._publicados.clear()
