"""Testes da Etapa 7.3 — HistoricoRepository e EmbeddingsIndexer.

Herméticos: SQLite em memória para banco, FakeEmbeddingProvider para embeddings.
Nenhum modelo real é carregado, nenhuma rede é acessada.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from ai.embeddings.fake_provider import FakeEmbeddingProvider
from ai.embeddings.historico_repository import HistoricoRepository
from ai.embeddings.indexer import EmbeddingsIndexer
from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
)
from core.infra.db import SessionFactory
from core.infra.repositories import LancamentoRepository


# =============================================================
# HELPERS
# =============================================================

@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


def _lancamento(
    empresa_id,
    descricao: str,
    categoria: str,
    status: StatusLancamento = StatusLancamento.APROVADO,
    conta_debito: str = "4.1.01.001",
    conta_credito: str = "1.1.01.002",
    valor: str = "100.00",
) -> Lancamento:
    lanc = Lancamento(
        empresa_id=empresa_id,
        descricao=descricao,
        categoria=categoria,
        status=status,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=date(2026, 6, 1),
        splits=[
            Split(
                conta=CodigoConta(conta_debito),
                natureza=NaturezaLancamento.DEBITO,
                valor=Dinheiro(Decimal(valor)),
            ),
            Split(
                conta=CodigoConta(conta_credito),
                natureza=NaturezaLancamento.CREDITO,
                valor=Dinheiro(Decimal(valor)),
            ),
        ],
    )
    return lanc


def _persistir(sf: SessionFactory, lancamento: Lancamento) -> None:
    with sf.session() as session:
        LancamentoRepository(session).salvar(lancamento)


# =============================================================
# HISTORICO REPOSITORY
# =============================================================

class TestHistoricoRepository:
    def test_retorna_candidatos_de_lancamentos_aprovados(self, sf) -> None:
        empresa_id = uuid4()
        _persistir(sf, _lancamento(empresa_id, "UBER DO BRASIL", "Transporte"))
        _persistir(sf, _lancamento(empresa_id, "IFOOD SERVICOS", "Alimentação"))

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_id)

        assert len(candidatos) == 2
        descricoes = {c.descricao for c in candidatos}
        assert "UBER DO BRASIL" in descricoes
        assert "IFOOD SERVICOS" in descricoes

    def test_nao_retorna_lancamentos_pendentes(self, sf) -> None:
        empresa_id = uuid4()
        _persistir(sf, _lancamento(empresa_id, "APROVADO", "Cat A"))
        _persistir(sf, _lancamento(empresa_id, "PENDENTE", "Cat B",
                                   status=StatusLancamento.PENDENTE))

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_id)

        assert len(candidatos) == 1
        assert candidatos[0].descricao == "APROVADO"

    def test_nao_retorna_lancamentos_de_outra_empresa(self, sf) -> None:
        empresa_a = uuid4()
        empresa_b = uuid4()
        _persistir(sf, _lancamento(empresa_a, "DA EMPRESA A", "Cat A"))
        _persistir(sf, _lancamento(empresa_b, "DA EMPRESA B", "Cat B"))

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_a)

        assert len(candidatos) == 1
        assert candidatos[0].descricao == "DA EMPRESA A"

    def test_historico_vazio_retorna_lista_vazia(self, sf) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_id)
        assert candidatos == []

    def test_extrai_contas_dos_splits(self, sf) -> None:
        empresa_id = uuid4()
        _persistir(sf, _lancamento(
            empresa_id, "TESTE CONTAS", "Cat",
            conta_debito="4.2.01.001",
            conta_credito="1.1.02.003",
        ))

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_id)

        assert candidatos[0].conta_debito == "4.2.01.001"
        assert candidatos[0].conta_credito == "1.1.02.003"

    def test_resposta_o_limit(self, sf) -> None:
        empresa_id = uuid4()
        for i in range(5):
            _persistir(sf, _lancamento(empresa_id, f"LANC {i}", "Cat"))

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(
                empresa_id, limit=3
            )

        assert len(candidatos) == 3

    def test_candidatos_sem_splits_sao_ignorados(self, sf) -> None:
        empresa_id = uuid4()
        lanc_sem_splits = Lancamento(
            empresa_id=empresa_id,
            descricao="SEM SPLITS",
            status=StatusLancamento.APROVADO,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        _persistir(sf, lanc_sem_splits)

        with sf.session() as session:
            candidatos = HistoricoRepository(session).obter_candidatos(empresa_id)

        assert len(candidatos) == 0


# =============================================================
# EMBEDDINGS INDEXER
# =============================================================

class TestEmbeddingsIndexer:
    def test_construir_com_historico_cria_plugin(self, sf) -> None:
        empresa_id = uuid4()
        _persistir(sf, _lancamento(empresa_id, "UBER", "Transporte"))
        _persistir(sf, _lancamento(empresa_id, "IFOOD", "Alimentação"))

        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)
        plugin = indexer.construir()

        assert plugin is not None
        assert indexer.total_candidatos == 2

    def test_construir_sem_historico_plugin_sem_candidatos(self, sf) -> None:
        empresa_id = uuid4()
        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)
        plugin = indexer.construir()

        assert plugin is not None
        assert indexer.total_candidatos == 0

    def test_plugin_sem_historico_retorna_precisa_revisao(self, sf) -> None:
        from core.domain.entities import (
            Dinheiro, Documento, FonteExtracao, TipoDocumento
        )
        empresa_id = uuid4()
        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)
        plugin = indexer.construir()

        doc = Documento(
            empresa_id=empresa_id,
            hash_sha256="a" * 64,
            nome_arquivo="test.csv",
            tipo=TipoDocumento.CSV,
            fonte_extracao=FonteExtracao.CSV,
            nome_emitente="NOVA EMPRESA",
            valor_total=Dinheiro(Decimal("100.00")),
        )
        s = plugin.sugerir_categoria(doc, None)
        assert s.precisa_revisao is True

    def test_embeddings_sao_computados_em_batch(self, sf) -> None:
        """encode_batch deve ser chamado uma vez com todos os textos."""
        empresa_id = uuid4()
        for desc in ["UBER", "IFOOD", "AMAZON"]:
            _persistir(sf, _lancamento(empresa_id, desc, "Teste"))

        from unittest.mock import patch

        provider = FakeEmbeddingProvider()
        original_encode_batch = provider.encode_batch

        chamadas: list = []

        def rastrear_batch(textos):
            chamadas.append(list(textos))
            return original_encode_batch(textos)

        with patch.object(provider, "encode_batch", side_effect=rastrear_batch):
            indexer = EmbeddingsIndexer(sf, provider, empresa_id)
            indexer.construir()

        assert len(chamadas) == 1
        assert len(chamadas[0]) == 3

    def test_candidatos_tem_embeddings_apos_construir(self, sf) -> None:
        empresa_id = uuid4()
        _persistir(sf, _lancamento(empresa_id, "UBER", "Transporte"))

        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)
        plugin = indexer.construir()

        assert all(len(c.embedding) > 0 for c in plugin._candidatos)

    def test_refresh_reconstroi_indice(self, sf) -> None:
        empresa_id = uuid4()
        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)

        # Primeiro: sem histórico
        indexer.construir()
        assert indexer.total_candidatos == 0

        # Adicionar lançamentos
        _persistir(sf, _lancamento(empresa_id, "NOVO LANCAMENTO", "Cat"))

        # Refresh: deve capturar o novo lançamento
        indexer.refresh()
        assert indexer.total_candidatos == 1

    def test_plugin_e_none_antes_de_construir(self, sf) -> None:
        empresa_id = uuid4()
        indexer = EmbeddingsIndexer(sf, FakeEmbeddingProvider(), empresa_id)
        assert indexer.plugin is None

    def test_isolamento_por_empresa_no_indexer(self, sf) -> None:
        empresa_a = uuid4()
        empresa_b = uuid4()
        _persistir(sf, _lancamento(empresa_a, "DA EMPRESA A", "Cat"))
        _persistir(sf, _lancamento(empresa_b, "DA EMPRESA B", "Cat"))

        provider = FakeEmbeddingProvider()
        indexer_a = EmbeddingsIndexer(sf, provider, empresa_a)
        indexer_a.construir()

        assert indexer_a.total_candidatos == 1


# =============================================================
# INTEGRAÇÃO: INDEXER + ORCHESTRATOR
# =============================================================

class TestIntegracaoIndexerOrchestrator:
    def test_orchestrator_usa_historico_real(self, sf) -> None:
        """Fluxo completo: histórico aprovado → índice → classificação."""
        from ai.embeddings.orchestrator import ClassifierOrchestrator
        from core.domain.entities import (
            Dinheiro, Documento, FonteExtracao, TipoDocumento
        )
        from core.rule_engine.classification_impl import RegrasDeterministicasPlugin

        empresa_id = uuid4()

        # Persistir lançamento aprovado no histórico
        _persistir(sf, _lancamento(
            empresa_id,
            descricao="UBER DO BRASIL TECNOLOGIA",
            categoria="Transporte",
            conta_debito="4.1.01.001",
            conta_credito="1.1.01.002",
        ))

        # Construir índice
        provider = FakeEmbeddingProvider()
        indexer = EmbeddingsIndexer(sf, provider, empresa_id)
        plugin_emb = indexer.construir()

        # Orchestrator: regras vazias (não cobre nada) + embeddings
        regras = RegrasDeterministicasPlugin(regras=[], fornecedores=[])
        orch = ClassifierOrchestrator(regras=regras, embeddings=plugin_emb)

        # Documento com descrição similar ao histórico
        doc = Documento(
            empresa_id=empresa_id,
            hash_sha256="b" * 64,
            nome_arquivo="test.csv",
            tipo=TipoDocumento.CSV,
            fonte_extracao=FonteExtracao.CSV,
            nome_emitente="UBER DO BRASIL TECNOLOGIA",
            valor_total=Dinheiro(Decimal("25.50")),
        )

        s = orch.sugerir_categoria(doc, None)

        # Deve vir do embedding (descrição idêntica ao histórico)
        assert s.metodo == "embedding"
        assert s.confidence > 0
        assert s.categoria == "Transporte"
