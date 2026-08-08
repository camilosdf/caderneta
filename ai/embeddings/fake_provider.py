"""FakeEmbeddingProvider — somente para testes herméticos (Etapa 7.1).

NÃO é uma implementação de produção. NÃO é TF-IDF sendo promovido a
embedding semântico. É um provider determinístico que permite testar
EmbeddingsPlugin, ClassifierOrchestrator e ExtractionPort sem instalar
sentence-transformers nem precisar de GPU ou rede.

A separação é explícita:
  - FakeEmbeddingProvider → testes
  - SentenceTransformerProvider → produção (Etapa 7.2)

Comportamento: representa cada texto como um bag-of-chars normalizado
de dimensão fixa. Semanticamente sem sentido, mas deterministicamente
correto para validar contratos e fluxo de dados.
"""

import hashlib
import math


class FakeEmbeddingProvider:
    """Provider determinístico para testes — satisfaz EmbeddingProvider Protocol.

    Gera vetores a partir de hash MD5 do texto, garantindo:
    - Mesmo texto → mesmo vetor (determinístico)
    - Textos diferentes → vetores diferentes (não colisão trivial)
    - Vetores normalizados (norma L2 = 1)
    - Dimensão fixa configurável
    - Zero dependências externas
    """

    def __init__(self, dimensao: int = 16) -> None:
        self._dimensao = dimensao

    @property
    def dimensao(self) -> int:
        return self._dimensao

    def encode(self, texto: str) -> list[float]:
        return self._hash_para_vetor(texto)

    def encode_batch(self, textos: list[str]) -> list[list[float]]:
        return [self._hash_para_vetor(t) for t in textos]

    def _hash_para_vetor(self, texto: str) -> list[float]:
        """Converte texto em vetor normalizado via MD5 expandido."""
        # Gerar bytes suficientes para preencher a dimensão desejada
        seed = texto.encode("utf-8")
        floats: list[float] = []
        i = 0
        while len(floats) < self._dimensao:
            h = hashlib.md5(seed + i.to_bytes(4, "little")).digest()
            # Cada byte → float [-1, 1]
            for b in h:
                floats.append((b / 127.5) - 1.0)
                if len(floats) == self._dimensao:
                    break
            i += 1

        # Normalizar L2
        norma = math.sqrt(sum(x * x for x in floats)) or 1.0
        return [x / norma for x in floats]
