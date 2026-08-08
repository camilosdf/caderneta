"""Testes do SentenceTransformerProvider (Etapa 7.2).

Herméticos: nenhum modelo é baixado. O SentenceTransformer real é
substituído por um mock que simula a interface necessária.

Por que mock e não FakeEmbeddingProvider?
  SentenceTransformerProvider é um adaptador entre ai/embeddings/
  e a biblioteca sentence-transformers. Os testes aqui validam:
  - importação lazy (modelo não carregado na construção)
  - configuração via CADERNETA_AI_MODELO_EMBEDDING
  - chamada correta da API do SentenceTransformer
  - normalização dos vetores retornados
  - tratamento de ImportError (biblioteca não instalada)

  FakeEmbeddingProvider testa o contrato. Estes testes testam
  o adaptador.
"""

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ai.embeddings.sentence_transformer_provider import (
    MODELO_PADRAO,
    SentenceTransformerProvider,
)
from core.ports.embedding import EmbeddingProvider


def _mock_modelo(dim: int = 8) -> MagicMock:
    """Cria um mock que simula SentenceTransformer."""
    mock = MagicMock()
    mock.get_sentence_embedding_dimension.return_value = dim

    def encode_side_effect(textos, normalize_embeddings=True, **kwargs):
        # SentenceTransformer aceita tanto string quanto lista
        if isinstance(textos, str):
            textos_lista = [textos]
            retorna_unico = True
        else:
            textos_lista = list(textos)
            retorna_unico = False

        rng = np.random.default_rng(42)
        result = rng.standard_normal((len(textos_lista), dim))
        if normalize_embeddings:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            result = result / np.maximum(norms, 1e-9)

        if retorna_unico:
            return result[0]  # SentenceTransformer retorna 1D para string única
        return result

    mock.encode.side_effect = encode_side_effect
    return mock


class TestSentenceTransformerProviderContrato:
    def test_satisfaz_protocolo(self) -> None:
        """SentenceTransformerProvider satisfaz EmbeddingProvider Protocol
        sem precisar carregar o modelo — só a existência dos métodos importa."""
        p = SentenceTransformerProvider(modelo="modelo-teste")
        assert isinstance(p, EmbeddingProvider)

    def test_modelo_nao_carregado_na_construcao(self) -> None:
        """Importação lazy — construtor não dispara download do modelo."""
        with patch("ai.embeddings.sentence_transformer_provider.SentenceTransformerProvider._obter_modelo") as m:
            provider = SentenceTransformerProvider(modelo="qualquer")
            m.assert_not_called()

    def test_modelo_nome_configuravel(self) -> None:
        p = SentenceTransformerProvider(modelo="meu-modelo")
        assert p.modelo_nome == "meu-modelo"

    def test_modelo_padrao_e_minilm(self) -> None:
        p = SentenceTransformerProvider()
        assert p.modelo_nome == MODELO_PADRAO

    def test_modelo_via_variavel_de_ambiente(self, monkeypatch) -> None:
        monkeypatch.setenv("CADERNETA_AI_MODELO_EMBEDDING", "modelo-do-env")
        p = SentenceTransformerProvider()
        assert p.modelo_nome == "modelo-do-env"


class TestSentenceTransformerProviderEncode:
    def test_encode_retorna_lista_de_floats(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            v = p.encode("UBER DO BRASIL")
        assert isinstance(v, list)
        assert all(isinstance(x, float) for x in v)

    def test_encode_dimensao_correta(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            v = p.encode("qualquer texto")
        assert len(v) == 8

    def test_encode_normalizado(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            v = p.encode("texto para normalizar")
        norma = math.sqrt(sum(x * x for x in v))
        assert abs(norma - 1.0) < 1e-5

    def test_encode_passa_normalize_embeddings_true(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            p.encode("texto")
        call_kwargs = mock_st.encode.call_args[1]
        assert call_kwargs.get("normalize_embeddings") is True


class TestSentenceTransformerProviderBatch:
    def test_encode_batch_retorna_lista_de_listas(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            result = p.encode_batch(["uber", "ifood", "mercado"])
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(v, list) and len(v) == 8 for v in result)

    def test_encode_batch_vazio(self) -> None:
        p = SentenceTransformerProvider(modelo="teste")
        assert p.encode_batch([]) == []

    def test_encode_batch_sem_progress_bar(self) -> None:
        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            p = SentenceTransformerProvider(modelo="teste")
            p.encode_batch(["a", "b"])
        call_kwargs = mock_st.encode.call_args[1]
        assert call_kwargs.get("show_progress_bar") is False


class TestSentenceTransformerProviderImportacao:
    def test_import_error_da_mensagem_clara(self) -> None:
        """Se sentence-transformers não estiver instalado, erro claro."""
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            p = SentenceTransformerProvider(modelo="teste")
            with pytest.raises(RuntimeError, match="sentence-transformers"):
                p.encode("texto")

    def test_modelo_carregado_uma_vez(self) -> None:
        """O modelo deve ser carregado apenas uma vez (lazy singleton)."""
        mock_st = _mock_modelo(dim=8)
        call_count = 0

        def fake_init(modelo, device):
            nonlocal call_count
            call_count += 1
            return mock_st

        with patch("sentence_transformers.SentenceTransformer", side_effect=fake_init):
            p = SentenceTransformerProvider(modelo="teste")
            p.encode("texto 1")
            p.encode("texto 2")
            p.encode_batch(["texto 3"])

        assert call_count == 1


class TestIntegracaoComEmbeddingsPlugin:
    """Valida que SentenceTransformerProvider pode ser injetado no EmbeddingsPlugin."""

    def test_plugin_aceita_provider_real(self) -> None:
        from ai.embeddings.embeddings_plugin import CandidatoHistorico, EmbeddingsPlugin

        mock_st = _mock_modelo(dim=8)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            provider = SentenceTransformerProvider(modelo="teste")

            candidatos = []
            for texto in ["UBER DO BRASIL", "IFOOD ALIMENTACAO"]:
                c = CandidatoHistorico(
                    descricao=texto,
                    categoria="Teste",
                    conta_debito="4.1.01.001",
                    conta_credito="1.1.01.002",
                )
                c.embedding = provider.encode(texto)
                candidatos.append(c)

            plugin = EmbeddingsPlugin(
                provider=provider,
                candidatos=candidatos,
            )

        assert len(plugin._candidatos) == 2
        assert all(len(c.embedding) == 8 for c in plugin._candidatos)

    def test_factory_de_lancamentos_com_provider_real(self) -> None:
        from ai.embeddings.embeddings_plugin import EmbeddingsPlugin

        mock_st = _mock_modelo(dim=8)
        lancamentos = [
            {"descricao": "UBER", "categoria": "Transporte",
             "conta_debito": "4.1.01.001", "conta_credito": "1.1.01.002"},
            {"descricao": "IFOOD", "categoria": "Alimentação",
             "conta_debito": "4.1.02.001", "conta_credito": "1.1.01.002"},
        ]

        with patch("sentence_transformers.SentenceTransformer", return_value=mock_st):
            provider = SentenceTransformerProvider(modelo="teste")
            plugin = EmbeddingsPlugin.de_lancamentos(provider, lancamentos)

        assert len(plugin._candidatos) == 2
        # encode_batch deve ter sido chamado uma vez com 2 textos
        mock_st.encode.assert_called_once()
