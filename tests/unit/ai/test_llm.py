"""Testes da Etapa 7.5 — LLMPort, FakeLLMProvider, LLMPlugin, Orchestrator completo.

Herméticos: sem Ollama, sem GPU, sem rede.
FakeLLMProvider satisfaz o Protocol — todos os contratos são validados
estruturalmente.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from ai.embeddings.fake_provider import FakeEmbeddingProvider
from ai.embeddings.embeddings_plugin import CandidatoHistorico, EmbeddingsPlugin
from ai.embeddings.orchestrator import ClassifierOrchestrator
from ai.llm.fake_provider import FakeLLMProvider
from ai.llm.llm_plugin import LLMPlugin
from core.domain.entities import Dinheiro, Documento, FonteExtracao, TipoDocumento
from core.ports.classification import ClassificationPort
from core.ports.llm import LLMPort
from core.rule_engine.classification_impl import RegrasDeterministicasPlugin


# =============================================================
# HELPERS
# =============================================================

def _doc(nome_emitente: str = "EMPRESA DESCONHECIDA") -> Documento:
    return Documento(
        empresa_id=uuid4(),
        hash_sha256="a" * 64,
        nome_arquivo="teste.csv",
        tipo=TipoDocumento.CSV,
        fonte_extracao=FonteExtracao.CSV,
        nome_emitente=nome_emitente,
        valor_total=Dinheiro(Decimal("100.00")),
    )


def _regras_vazias() -> RegrasDeterministicasPlugin:
    return RegrasDeterministicasPlugin(regras=[], fornecedores=[])


def _embeddings_vazios() -> EmbeddingsPlugin:
    return EmbeddingsPlugin(
        provider=FakeEmbeddingProvider(),
        candidatos=[],
    )


# =============================================================
# LLMPort — contrato
# =============================================================

class TestLLMPort:
    def test_fake_satisfaz_protocolo(self) -> None:
        fake = FakeLLMProvider()
        assert isinstance(fake, LLMPort)

    def test_fake_tem_modelo(self) -> None:
        fake = FakeLLMProvider(modelo_nome="meu-modelo")
        assert fake.modelo == "meu-modelo"

    def test_fake_completar_retorna_string(self) -> None:
        fake = FakeLLMProvider(resposta_padrao='{"ok": true}')
        resp = fake.completar("qualquer prompt")
        assert isinstance(resp, str)
        assert resp == '{"ok": true}'

    def test_fake_registra_chamadas(self) -> None:
        fake = FakeLLMProvider()
        fake.completar("prompt 1")
        fake.completar("prompt 2")
        assert len(fake.chamadas) == 2
        assert "prompt 1" in fake.chamadas[0]


# =============================================================
# LLMPlugin
# =============================================================

class TestLLMPlugin:
    def test_satisfaz_classification_port(self) -> None:
        plugin = LLMPlugin(provider=FakeLLMProvider())
        assert isinstance(plugin, ClassificationPort)

    def test_resposta_json_valida_retorna_sugestao(self) -> None:
        resposta = '{"categoria": "Transporte", "conta_debito": "4.1.01.001", "conta_credito": "1.1.01.002", "confidence": 0.88, "motivo": "Viagem de negócios"}'
        plugin = LLMPlugin(provider=FakeLLMProvider(resposta_padrao=resposta))
        s = plugin.sugerir_categoria(_doc(), None)

        assert s.categoria == "Transporte"
        assert s.confidence == pytest.approx(0.88)
        assert "llm:" in s.metodo

    def test_confidence_nunca_atinge_1(self) -> None:
        resposta = '{"categoria": "X", "conta_debito": "4.1", "conta_credito": "1.1", "confidence": 1.0, "motivo": "X"}'
        plugin = LLMPlugin(provider=FakeLLMProvider(resposta_padrao=resposta))
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.confidence < 1.0

    def test_confidence_clipada_em_0_98(self) -> None:
        resposta = '{"categoria": "X", "conta_debito": "4.1", "conta_credito": "1.1", "confidence": 0.99, "motivo": "X"}'
        plugin = LLMPlugin(provider=FakeLLMProvider(resposta_padrao=resposta))
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.confidence <= 0.98

    def test_json_invalido_retorna_fallback(self) -> None:
        plugin = LLMPlugin(provider=FakeLLMProvider(resposta_padrao="não é json"))
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is True
        assert s.confidence == 0.0

    def test_confidence_baixa_precisa_revisao(self) -> None:
        resposta = '{"categoria": "X", "conta_debito": "4.1", "conta_credito": "1.1", "confidence": 0.5, "motivo": "incerto"}'
        plugin = LLMPlugin(
            provider=FakeLLMProvider(resposta_padrao=resposta),
            threshold_revisao=0.75,
        )
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is True

    def test_confidence_alta_sem_revisao(self) -> None:
        resposta = '{"categoria": "Transporte", "conta_debito": "4.1.01.001", "conta_credito": "1.1.01.002", "confidence": 0.90, "motivo": "claro"}'
        plugin = LLMPlugin(
            provider=FakeLLMProvider(resposta_padrao=resposta),
            threshold_revisao=0.75,
        )
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is False

    def test_erro_no_provider_retorna_fallback(self) -> None:
        fake = FakeLLMProvider()
        fake.completar = lambda *_, **__: (_ for _ in ()).throw(RuntimeError("timeout"))
        plugin = LLMPlugin(provider=fake)
        s = plugin.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is True
        assert s.confidence == 0.0

    def test_prompt_inclui_contexto_do_documento(self) -> None:
        fake = FakeLLMProvider(resposta_padrao='{"categoria": "X", "conta_debito": "4.1", "conta_credito": "1.1", "confidence": 0.8, "motivo": "X"}')
        plugin = LLMPlugin(provider=fake)
        plugin.sugerir_categoria(_doc("UBER DO BRASIL"), None)

        assert len(fake.chamadas) == 1
        assert "UBER DO BRASIL" in fake.chamadas[0]

    def test_normalizar_fornecedor_retorna_precisa_revisao(self) -> None:
        plugin = LLMPlugin(provider=FakeLLMProvider())
        r = plugin.normalizar_fornecedor("UBER DO BRASIL")
        assert r.precisa_revisao is True
        assert r.metodo == "llm"


# =============================================================
# ClassifierOrchestrator — três camadas
# =============================================================

class TestOrchestratorComLLM:
    @pytest.fixture
    def llm_plugin(self) -> LLMPlugin:
        resposta = '{"categoria": "LLM Cat", "conta_debito": "4.1.01.001", "conta_credito": "1.1.01.002", "confidence": 0.82, "motivo": "desambiguado"}'
        return LLMPlugin(
            provider=FakeLLMProvider(resposta_padrao=resposta),
            threshold_revisao=0.75,
        )

    def test_llm_ativado_quando_regras_e_embeddings_nao_cobrem(
        self, llm_plugin
    ) -> None:
        orch = ClassifierOrchestrator(
            regras=_regras_vazias(),
            embeddings=_embeddings_vazios(),
            llm=llm_plugin,
        )
        s = orch.sugerir_categoria(_doc(), None)
        assert "llm:" in s.metodo
        assert s.categoria == "LLM Cat"

    def test_regras_tem_precedencia_sobre_llm(self, llm_plugin) -> None:
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2

        regra = RegraClassificacaoV2(
            nome="Uber",
            condicao={"descricao_contains_any": ["UBER"]},
            categoria="Transporte",
            conta_debito=CodigoConta("4.1.01.001"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=10,
            criada_por="teste",
        )
        regras = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        orch = ClassifierOrchestrator(regras=regras, llm=llm_plugin)

        s = orch.sugerir_categoria(_doc("UBER VIAGENS"), None)
        assert s.metodo == "regra_deterministica"
        assert s.confidence == 1.0

    def test_embeddings_tem_precedencia_sobre_llm(self, llm_plugin) -> None:
        provider = FakeEmbeddingProvider()
        candidato = CandidatoHistorico(
            descricao="EMPRESA DESCONHECIDA",
            categoria="Embedding Cat",
            conta_debito="4.1.01.001",
            conta_credito="1.1.01.002",
        )
        candidato.embedding = provider.encode("EMPRESA DESCONHECIDA")

        emb_plugin = EmbeddingsPlugin(
            provider=provider,
            candidatos=[candidato],
            threshold_classificar=0.50,
            threshold_revisao=0.30,
        )
        orch = ClassifierOrchestrator(
            regras=_regras_vazias(),
            embeddings=emb_plugin,
            llm=llm_plugin,
            threshold_aceitar_embedding=0.30,
        )
        s = orch.sugerir_categoria(_doc("EMPRESA DESCONHECIDA"), None)
        assert s.metodo == "embedding"

    def test_llm_nao_consultado_sem_llm_configurado(self) -> None:
        fake = FakeLLMProvider()
        orch = ClassifierOrchestrator(
            regras=_regras_vazias(),
            embeddings=_embeddings_vazios(),
            llm=None,
        )
        orch.sugerir_categoria(_doc(), None)
        assert len(fake.chamadas) == 0

    def test_orchestrator_sem_llm_compativel_com_7_1(self) -> None:
        """Sem LLM, comportamento é idêntico ao da 7.1."""
        orch = ClassifierOrchestrator(
            regras=_regras_vazias(),
            embeddings=None,
            llm=None,
        )
        s = orch.sugerir_categoria(_doc(), None)
        assert s.precisa_revisao is True

    def test_orchestrator_satisfaz_classification_port(self) -> None:
        orch = ClassifierOrchestrator(regras=_regras_vazias())
        assert isinstance(orch, ClassificationPort)

    def test_llm_com_baixa_confidence_ainda_retorna_sugestao(self) -> None:
        """LLM com baixa confiança não bloqueia — retorna precisa_revisao=True."""
        resposta_baixa = '{"categoria": "Incerto", "conta_debito": "4.1", "conta_credito": "1.1", "confidence": 0.3, "motivo": "incerto"}'
        llm_baixo = LLMPlugin(
            provider=FakeLLMProvider(resposta_padrao=resposta_baixa),
            threshold_revisao=0.75,
        )
        orch = ClassifierOrchestrator(
            regras=_regras_vazias(),
            embeddings=_embeddings_vazios(),
            llm=llm_baixo,
        )
        s = orch.sugerir_categoria(_doc(), None)
        # Mesmo com confiança baixa, LLM retornou algo — não volta fallback vazio
        assert "llm:" in s.metodo
        assert s.precisa_revisao is True
