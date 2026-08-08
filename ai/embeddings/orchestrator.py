"""ClassifierOrchestrator — Etapa 7.1.

Implementa ClassificationPort via composição de múltiplos plugins.
A precedência (regras → embeddings → fallback) vive aqui, não dentro
de nenhum plugin individual.

Princípio arquitetural (do parecer de Etapa 7):
  A composição é responsabilidade do Orchestrator, não dos plugins.
  Cada plugin tem uma responsabilidade única e não conhece os outros.

Também satisfaz ClassificationPort via duck typing — pode ser injetado
em qualquer lugar que aceite um ClassificationPort.
"""

from typing import Optional

from core.domain.entities import Documento, Fornecedor
from core.ports.classification import (
    ClassificationPort,
    ResultadoNormalizacao,
    Sugestao,
)


class ClassifierOrchestrator:
    """Orquestra a sequência de classificação conforme ADR 003:

    1. RegrasDeterministicasPlugin — confidence=1.0, precisa_revisao=False
    2. EmbeddingsPlugin — confidence variável, precisa_revisao condicional
    3. Fallback — sem sugestão útil, precisa_revisao=True

    Satisfaz ClassificationPort via duck typing.
    """

    def __init__(
        self,
        regras: ClassificationPort,
        embeddings: Optional[ClassificationPort] = None,
        threshold_aceitar_embedding: float = 0.70,
    ) -> None:
        """
        Args:
            regras: plugin determinístico (RegrasDeterministicasPlugin).
                    Obrigatório — é a primeira e mais importante camada.
            embeddings: plugin semântico (EmbeddingsPlugin). Opcional —
                        quando ausente o Orchestrator se comporta igual
                        ao plugin de regras puro (comportamento atual de
                        todas as etapas anteriores à Etapa 7).
            threshold_aceitar_embedding: confidence mínima da sugestão
                        de embeddings para ser aceita pelo Orchestrator.
                        Abaixo disso, retorna a sugestão das regras
                        (que é o fallback determinístico), mesmo que as
                        regras não tenham coberto o caso.
        """
        self._regras = regras
        self._embeddings = embeddings
        self._threshold = threshold_aceitar_embedding

    # ── ClassificationPort ────────────────────────────────────────────────

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Optional[Fornecedor],
    ) -> Sugestao:
        """Aplica regras primeiro; se não cobriu, tenta embeddings."""
        sugestao_regra = self._regras.sugerir_categoria(documento, fornecedor)

        # Regras determinísticas sempre têm precedência absoluta
        if sugestao_regra.confidence >= 1.0 and not sugestao_regra.precisa_revisao:
            return sugestao_regra

        # Sem camada de embeddings — retorna o resultado das regras
        if self._embeddings is None:
            return sugestao_regra

        sugestao_emb = self._embeddings.sugerir_categoria(documento, fornecedor)

        if sugestao_emb.confidence >= self._threshold and not sugestao_emb.precisa_revisao:
            return sugestao_emb

        # Nenhum cobriu com confiança suficiente — retorna o que tiver mais
        # informação: se o embedding encontrou algo (mesmo baixa confiança),
        # prefere-o ao fallback das regras (que seria genérico). Caso contrário,
        # mantém o fallback das regras.
        if sugestao_emb.confidence > 0:
            return sugestao_emb

        return sugestao_regra

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normaliza tentando primeiro por regras (alias exato), depois embeddings."""
        resultado_regra = self._regras.normalizar_fornecedor(nome_raw)

        if not resultado_regra.precisa_revisao:
            return resultado_regra

        if self._embeddings is None:
            return resultado_regra

        resultado_emb = self._embeddings.normalizar_fornecedor(nome_raw)

        if resultado_emb.confidence >= self._threshold:
            return resultado_emb

        # Retorna o da regra — ao menos tem o nome bruto como canônico
        return resultado_regra
