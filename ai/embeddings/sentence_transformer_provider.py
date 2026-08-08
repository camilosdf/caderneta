"""SentenceTransformerProvider — provider real para produção (Etapa 7.2).

Implementa EmbeddingProvider usando sentence-transformers.
Satisfaz o Protocol via duck typing — não herda de nenhuma classe base.

Modelo padrão: paraphrase-multilingual-MiniLM-L12-v2
  - Multilíngue, incluindo português
  - Leve (~90 MB, 384 dimensões)
  - Funciona sem GPU
  - Adequado para validar a arquitetura antes de migrar para o modelo
    de produção definido no plano: rufimelo/bert-large-portuguese-cased-sts

Modelo-alvo de produção (benchmark posterior à Etapa 7.2):
  rufimelo/bert-large-portuguese-cased-sts
  - Treinado especificamente para similaridade semântica em português BR
  - 1024 dimensões, mais pesado
  - Requer benchmark controlado contra MiniLM antes de migrar

Importação lazy: sentence-transformers só é importado quando o provider
é inicializado pela primeira vez, não quando o módulo é carregado.
Isso garante que o Core continua passando em todos os testes sem
sentence-transformers instalado (ADR 003 — Core independente de IA).

Configuração: CADERNETA_AI_MODELO_EMBEDDING controla qual modelo usar.
"""

import os

MODELO_PADRAO = "paraphrase-multilingual-MiniLM-L12-v2"
MODELO_PRODUCAO = "rufimelo/bert-large-portuguese-cased-sts"


class SentenceTransformerProvider:
    """Provider de embedding via sentence-transformers.

    Importação lazy — o modelo é carregado apenas na primeira chamada
    a encode() ou encode_batch(). Permite injetar o provider sem
    disparar o download do modelo em testes que não precisam dele.
    """

    def __init__(
        self,
        modelo: str | None = None,
        device: str = "cpu",
        _modelo_instancia=None,  # injeção direta para testes — não usar em produção
    ) -> None:
        """
        Args:
            modelo: nome do modelo HuggingFace. None → lê
                    CADERNETA_AI_MODELO_EMBEDDING, com fallback para
                    paraphrase-multilingual-MiniLM-L12-v2.
            device: "cpu" (padrão), "cuda", ou "mps" (Apple Silicon).
            _modelo_instancia: instância já carregada (mock em testes).
                    Prefixo _ sinaliza que não é API pública.
        """
        self._modelo_nome = (
            modelo
            or os.getenv("CADERNETA_AI_MODELO_EMBEDDING", MODELO_PADRAO)
        )
        self._device = device
        self._modelo = _modelo_instancia  # None em produção, mock em testes

    @property
    def dimensao(self) -> int:
        """Dimensão do vetor — força o carregamento do modelo."""
        return self._obter_modelo().get_sentence_embedding_dimension()

    def encode(self, texto: str) -> list[float]:
        """Converte um texto em vetor normalizado."""
        modelo = self._obter_modelo()
        vetor = modelo.encode(
            texto,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vetor.tolist()

    def encode_batch(self, textos: list[str]) -> list[list[float]]:
        """Batch de textos — mais eficiente que chamar encode() em loop."""
        if not textos:
            return []
        modelo = self._obter_modelo()
        vetores = modelo.encode(
            textos,
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=32,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vetores]

    @property
    def modelo_nome(self) -> str:
        """Nome do modelo carregado."""
        return self._modelo_nome

    # ── Internos ──────────────────────────────────────────────────────────

    def _obter_modelo(self):
        """Carrega o modelo na primeira chamada (importação lazy)."""
        if self._modelo is not None:
            return self._modelo

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as err:
            raise RuntimeError(
                "sentence-transformers não instalado. "
                "Para usar SentenceTransformerProvider, instale o grupo 'ai': "
                "pip install caderneta[ai]\n"
                "Este provider pertence a ai/, nunca é importado pelo core/."
            ) from err

        self._modelo = SentenceTransformer(
            self._modelo_nome,
            device=self._device,
        )
        return self._modelo
