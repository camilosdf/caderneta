"""Porta de embedding — Etapa 7.1.

Define o contrato que qualquer provider de embeddings deve satisfazer.
O EmbeddingsPlugin não sabe qual modelo está por trás: pode ser
SentenceTransformerProvider (7.2), FakeEmbeddingProvider (testes),
ou no futuro pgvector diretamente.

Mantido em core/ports/ porque é um contrato que o core define e
ai/ implementa — mesma disciplina de ClassificationPort.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contrato de provider de embeddings.

    Responsabilidade única: converter texto em vetor de floats.
    Não decide, não classifica, não normaliza — só representa.
    """

    @property
    def dimensao(self) -> int:
        """Dimensão do vetor de saída — constante para um dado modelo."""
        ...

    def encode(self, texto: str) -> list[float]:
        """Converte um texto em vetor de embedding normalizado (L2=1).

        O vetor retornado deve ser normalizado para que o produto interno
        seja equivalente à similaridade do cosseno — simplifica o ranking
        de candidatos sem precisar calcular normas adicionais.
        """
        ...

    def encode_batch(self, textos: list[str]) -> list[list[float]]:
        """Versão em batch para indexação eficiente de histórico.

        Implementação padrão: pode ser sobrescrita pelo provider para
        aproveitar batching nativo do modelo.
        """
        ...
