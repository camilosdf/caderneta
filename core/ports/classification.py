"""Contratos (Ports) para classificação e normalização.

O Core define estas interfaces. AI implementa. Core nunca importa AI.
Baseado em typing.Protocol — duck typing estrutural sem herança.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from core.domain.entities import (
    CodigoConta,
    ConfidenceScore,
    Documento,
    Fornecedor,
    RegraClassificacao,
)


@dataclass
class Sugestao:
    """Resultado de uma sugestão de classificação (por regra ou por IA)."""
    categoria: Optional[str]
    conta_debito: Optional[CodigoConta]
    conta_credito: Optional[CodigoConta]
    centro_custo: Optional[str]
    confidence: float                      # 0.0 a 1.0
    metodo: str                            # ex: "regra", "historico_kb", "embedding", "llm"
    regra_aplicada_id: Optional[UUID] = None
    versao_regra: Optional[int] = None
    precisa_revisao: bool = False
    motivo: Optional[str] = None


@dataclass
class ResultadoNormalizacao:
    """Resultado da normalização de um nome de fornecedor."""
    fornecedor_id: Optional[UUID]
    nome_canonico: str
    confidence: float
    metodo: str  # "exato", "alias", "prefixo", "embedding", "llm", "novo"
    precisa_revisao: bool = False


@runtime_checkable
class ClassificationPort(Protocol):
    """Porta de classificação contábil.

    Qualquer objeto que implemente este contrato pode ser injetado
    no Motor Contábil, seja baseado em regras ou em IA.
    """

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Optional[Fornecedor],
    ) -> Sugestao:
        """Sugere categoria, contas e centro de custo para um documento."""
        ...

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normaliza o nome bruto de um fornecedor para o nome canônico."""
        ...


@runtime_checkable
class ExtractionPort(Protocol):
    """Porta de extração de campos de documentos não estruturados."""

    def extrair_campos(
        self,
        texto: str,
        tipo_documento: str,
    ) -> dict[str, tuple[str, float]]:
        """
        Extrai campos do texto e retorna dict {campo: (valor, confidence)}.
        Usado apenas quando o parser determinístico não consegue extrair o campo.
        """
        ...
