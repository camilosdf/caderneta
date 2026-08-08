"""Testes da Etapa 7.1 — EmbeddingProvider, EmbeddingsPlugin, ClassifierOrchestrator.

Herméticos: sem sentence-transformers, sem GPU, sem rede.
FakeEmbeddingProvider satisfaz o Protocol — todos os contratos
são validados estruturalmente, não dependem do modelo real.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from ai.embeddings.embeddings_plugin import (
    CandidatoHistorico,
    EmbeddingsPlugin,
    _produto_interno,
    _sim_para_confidence,
)
from ai.embeddings.fake_provider import FakeEmbeddingProvider
from ai.embeddings.orchestrator import ClassifierOrchestrator
from core.domain.entities import Dinheiro, Documento, FonteExtracao, TipoDocumento
from core.ports.classification import Sugestao
from core.ports.embedding import EmbeddingProvider
from core.rule_engine.classification_impl import RegrasDeterministicasPlugin


# =============================================================
# HELPERS
# =============================================================

def _doc(nome_emitente="UBER DO BRASIL") -> Documento:
    return Documento(
        empresa_id=uuid4(),
        hash_sha256="a" * 64,
        nome_arquivo="teste.csv",
        tipo=TipoDocumento.CSV,
        fonte_extracao=FonteExtracao.CSV,
        nome_emitente=nome_emitente,
        valor_total=Dinheiro(Decimal("100.00")),
    )


def _candidato(descricao: str, categoria: str, provider: FakeEmbeddingProvider) -> CandidatoHistorico:
    c = CandidatoHistorico(
        descricao=descricao,
        categoria=categoria,
        conta_debito="4.1.01.001",
        conta_credito="1.1.01.002",
    )
    c.embedding = provider.encode(descricao)
    return c


# =============================================================
# FAKE EMBEDDING PROVIDER
# =============================================================

class TestFakeEmbeddingProvider:
    def test_satisfaz_protocolo(self) -> None:
        p = FakeEmbeddingProvider()
        assert isinstance(p, EmbeddingProvider)

    def test_dimensao_configuravel(self) -> None:
        assert FakeEmbeddingProvider(dimensao=8).dimensao == 8
        assert FakeEmbeddingProvider(dimensao=32).dimensao == 32

    def test_encode_retorna_dimensao_correta(self) -> None:
        p = FakeEmbeddingProvider(dimensao=16)
        v = p.encode("qualquer texto")
        assert len(v) == 16

    def test_encode_e_deterministico(self) -> None:
        p = FakeEmbeddingProvider()
        assert p.encode("uber") == p.encode("uber")

    def test_textos_diferentes_geram_vetores_diferentes(self) -> None:
        p = FakeEmbeddingProvider()
        assert p.encode("uber") != p.encode("ifood")

    def test_vetor_e_normalizado(self) -> None:
        import math
        p = FakeEmbeddingProvider(dimensao=16)
        v = p.encode("texto qualquer")
        norma = math.sqrt(sum(x * x for x in v))
        assert abs(norma - 1.0) < 1e-6

    def test_encode_batch(self) -> None:
        p = FakeEmbeddingProvider(dimensao=8)
        textos = ["uber", "ifood", "mercado"]
        batch = p.encode_batch(textos)
        assert len(batch) == 3
        assert all(len(v) == 8 for v in batch)
        assert batch[0] == p.encode("uber")


# =============================================================
# EMBEDDINGS PLUGIN
# =============================================================

class TestEmbeddingsPluginSemHistorico:
    def test_sem_historico_retorna_precisa_revisao(self) -> None:
        provider = FakeEmbeddingProvider()
        plugin = EmbeddingsPlugin(provider=provider, candidatos=[])
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is True
        assert s.confidence == 0.0

    def test_sem_historico_metodo_e_embedding(self) -> None:
        provider = FakeEmbeddingProvider()
        plugin = EmbeddingsPlugin(provider=provider)
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.metodo == "embedding"


class TestEmbeddingsPluginComHistorico:
    @pytest.fixture
    def provider(self) -> FakeEmbeddingProvider:
        return FakeEmbeddingProvider()

    @pytest.fixture
    def plugin(self, provider) -> EmbeddingsPlugin:
        candidatos = [
            _candidato("UBER DO BRASIL", "Transporte", provider),
            _candidato("IFOOD SERVICOS DE ALIMENTACAO", "Alimentação", provider),
            _candidato("AMAZON WEB SERVICES", "Tecnologia", provider),
        ]
        return EmbeddingsPlugin(
            provider=provider,
            candidatos=candidatos,
            threshold_classificar=0.85,
            threshold_revisao=0.70,
        )

    def test_texto_identico_alta_confidence(self, plugin, provider) -> None:
        """Texto idêntico ao candidato → maior similaridade possível."""
        s = plugin.sugerir_categoria(_doc("UBER DO BRASIL"), None)
        assert s.confidence > 0.0
        assert s.metodo == "embedding"

    def test_encontra_categoria_correspondente(self, plugin) -> None:
        s = plugin.sugerir_categoria(_doc("UBER DO BRASIL"), None)
        assert s.categoria == "Transporte"

    def test_confianca_entre_0_e_1(self, plugin) -> None:
        s = plugin.sugerir_categoria(_doc("UBER DO BRASIL"), None)
        assert 0.0 <= s.confidence <= 1.0

    def test_regras_nao_tem_confidence_1_em_embedding(self, plugin) -> None:
        """Embedding nunca deve retornar confidence=1.0 — só regras determinísticas."""
        s = plugin.sugerir_categoria(_doc("UBER DO BRASIL"), None)
        assert s.confidence < 1.0

    def test_texto_muito_diferente_encaminha_revisao(self, plugin) -> None:
        s = plugin.sugerir_categoria(_doc("XYZABC123QWERTY"), None)
        assert s.precisa_revisao is True

    def test_normalizar_fornecedor_sem_historico(self, provider) -> None:
        plugin = EmbeddingsPlugin(provider=provider, candidatos=[])
        r = plugin.normalizar_fornecedor("UBER DO BRASIL")
        assert r.precisa_revisao is True

    def test_factory_de_lancamentos(self, provider) -> None:
        lancamentos = [
            {"descricao": "UBER", "categoria": "Transporte",
             "conta_debito": "4.1.01.001", "conta_credito": "1.1.01.002"},
            {"descricao": "IFOOD", "categoria": "Alimentação",
             "conta_debito": "4.1.02.001", "conta_credito": "1.1.01.002"},
        ]
        plugin = EmbeddingsPlugin.de_lancamentos(provider, lancamentos)
        assert len(plugin._candidatos) == 2
        assert all(len(c.embedding) > 0 for c in plugin._candidatos)


# =============================================================
# CLASSIFIER ORCHESTRATOR
# =============================================================

class TestClassifierOrchestrator:
    @pytest.fixture
    def regras(self) -> RegrasDeterministicasPlugin:
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        from core.domain.entities import CodigoConta

        regra = RegraClassificacaoV2(
            nome="Uber",
            condicao={"descricao_contains_any": ["UBER"]},
            categoria="Transporte",
            conta_debito=CodigoConta("4.1.01.001"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=10,
            criada_por="teste",
        )
        return RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])

    @pytest.fixture
    def provider(self) -> FakeEmbeddingProvider:
        return FakeEmbeddingProvider()

    @pytest.fixture
    def embeddings(self, provider) -> EmbeddingsPlugin:
        candidatos = [
            _candidato("IFOOD SERVICOS", "Alimentação", provider),
            _candidato("MERCADO LIVRE PAGAMENTOS", "Compras Online", provider),
        ]
        return EmbeddingsPlugin(
            provider=provider,
            candidatos=candidatos,
            threshold_classificar=0.85,
            threshold_revisao=0.60,
        )

    def test_regra_tem_precedencia_sobre_embedding(self, regras, embeddings) -> None:
        """Quando regra cobre, não deve delegar para embeddings."""
        orch = ClassifierOrchestrator(regras=regras, embeddings=embeddings)
        s = orch.sugerir_categoria(_doc("UBER VIAGENS"), None)
        assert s.metodo == "regra_deterministica"
        assert s.confidence == 1.0

    def test_embedding_ativado_quando_regra_nao_cobre(self, regras, embeddings) -> None:
        """Quando regra não cobre, deve tentar embeddings."""
        orch = ClassifierOrchestrator(regras=regras, embeddings=embeddings)
        s = orch.sugerir_categoria(_doc("IFOOD SERVICOS"), None)
        assert s.metodo == "embedding"

    def test_sem_embeddings_retorna_resultado_regras(self, regras) -> None:
        """Sem camada de embeddings, comportamento igual a antes da Etapa 7."""
        orch = ClassifierOrchestrator(regras=regras, embeddings=None)
        s = orch.sugerir_categoria(_doc("MERCADO LIVRE"), None)
        # Não cobertas por regras, sem embeddings → retorna fallback do plugin de regras
        assert s.metodo in ("regra_deterministica", "fallback")
        assert s.precisa_revisao is True

    def test_orchestrator_satisfaz_classification_port(self, regras) -> None:
        from core.ports.classification import ClassificationPort
        orch = ClassifierOrchestrator(regras=regras)
        assert isinstance(orch, ClassificationPort)

    def test_normalizar_fornecedor_delega_corretamente(self, regras, embeddings) -> None:
        orch = ClassifierOrchestrator(regras=regras, embeddings=embeddings)
        r = orch.normalizar_fornecedor("UBER DO BRASIL")
        # regras devem cobrir exato/alias antes do embedding
        assert r is not None


# =============================================================
# UTILITÁRIOS INTERNOS
# =============================================================

class TestUtilitariosInternos:
    def test_produto_interno_vetores_identicos(self) -> None:
        v = [0.6, 0.8]
        assert abs(_produto_interno(v, v) - 1.0) < 1e-9

    def test_produto_interno_ortogonais(self) -> None:
        assert abs(_produto_interno([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_sim_para_confidence_limites(self) -> None:
        assert _sim_para_confidence(0.0) == 0.0
        assert _sim_para_confidence(1.0) < 1.0     # nunca atinge 1.0
        assert _sim_para_confidence(0.85) > 0.0

    def test_sim_para_confidence_monotona(self) -> None:
        """Maior similaridade → maior confidence."""
        assert _sim_para_confidence(0.9) > _sim_para_confidence(0.7)

    def test_sim_negativa_clipa_em_zero(self) -> None:
        assert _sim_para_confidence(-0.5) == 0.0
