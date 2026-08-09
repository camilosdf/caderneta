"""ClassifierOrchestrator — Etapa 7.1 / 7.5.

Implementa ClassificationPort via composição de múltiplos plugins.
A precedência (regras → embeddings → LLM → fallback) vive aqui,
não dentro de nenhum plugin individual.

Princípio arquitetural (do parecer de Etapa 7):
  A composição é responsabilidade do Orchestrator, não dos plugins.
  Cada plugin tem uma responsabilidade única e não conhece os outros.

Também satisfaz ClassificationPort via duck typing — pode ser injetado
em qualquer lugar que aceite um ClassificationPort.
"""

from core.domain.entities import Documento, Fornecedor
from core.ports.classification import (
    ClassificationPort,
    ResultadoNormalizacao,
    Sugestao,
)


class ClassifierOrchestrator:
    """Orquestra a sequência de classificação conforme ADR 003:

    1. RegrasDeterministicasPlugin — confidence=1.0, precisa_revisao=False
    2. EmbeddingsPlugin            — confidence variável, threshold configurável
    3. LLMPlugin                   — desambiguação, precisa_revisao quando baixa conf.
    4. Fallback                    — sem sugestão útil, precisa_revisao=True

    Satisfaz ClassificationPort via duck typing.
    """

    def __init__(
        self,
        regras: ClassificationPort,
        embeddings: ClassificationPort | None = None,
        llm: ClassificationPort | None = None,
        threshold_aceitar_embedding: float = 0.70,
        threshold_aceitar_llm: float = 0.75,
    ) -> None:
        self._regras = regras
        self._embeddings = embeddings
        self._llm = llm
        self._threshold_emb = threshold_aceitar_embedding
        self._threshold_llm = threshold_aceitar_llm

    # ── ClassificationPort ────────────────────────────────────────────────

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Fornecedor | None,
    ) -> Sugestao:
        """Aplica as camadas em sequência: regras → embeddings → LLM."""
        # ── Camada 1: regras determinísticas ─────────────────────────────
        sugestao_regra = self._regras.sugerir_categoria(documento, fornecedor)
        if sugestao_regra.confidence >= 1.0 and not sugestao_regra.precisa_revisao:
            return sugestao_regra

        # ── Camada 2: embeddings ──────────────────────────────────────────
        sugestao_emb: Sugestao | None = None
        if self._embeddings is not None:
            sugestao_emb = self._embeddings.sugerir_categoria(documento, fornecedor)
            if sugestao_emb.confidence >= self._threshold_emb and not sugestao_emb.precisa_revisao:
                return sugestao_emb

        # ── Camada 3: LLM (desambiguação) ────────────────────────────────
        if self._llm is not None:
            sugestao_llm = self._llm.sugerir_categoria(documento, fornecedor)
            if sugestao_llm.confidence >= self._threshold_llm:
                return sugestao_llm
            if sugestao_llm.confidence > 0:
                return sugestao_llm

        # ── Fallback ──────────────────────────────────────────────────────
        if sugestao_emb is not None and sugestao_emb.confidence > 0:
            return sugestao_emb
        return sugestao_regra

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normaliza tentando regras → embeddings → LLM → fallback."""
        resultado_regra = self._regras.normalizar_fornecedor(nome_raw)
        if not resultado_regra.precisa_revisao:
            return resultado_regra

        if self._embeddings is not None:
            resultado_emb = self._embeddings.normalizar_fornecedor(nome_raw)
            if resultado_emb.confidence >= self._threshold_emb:
                return resultado_emb

        if self._llm is not None:
            resultado_llm = self._llm.normalizar_fornecedor(nome_raw)
            if resultado_llm.confidence >= self._threshold_llm:
                return resultado_llm

        return resultado_regra
