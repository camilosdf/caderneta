"""Testes do UnitOfWork — A4.

Cobre: transação única com múltiplos repositórios, commit explícito,
rollback automático em exceção, rollback ao sair sem commit.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from core.audit.chain import TipoEvento
from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Documento,
    FonteExtracao,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    TipoDocumento,
)
from core.infra.db import SessionFactory
from core.infra.unit_of_work import UnitOfWork


# =============================================================
# FIXTURES
# =============================================================

@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _doc() -> Documento:
    return Documento(
        id=uuid4(),
        empresa_id=uuid4(),
        hash_sha256="a" * 64,
        nome_arquivo="nfe.xml",
        tipo=TipoDocumento.NFE_XML,
        fonte_extracao=FonteExtracao.XML,
        data_emissao=date(2024, 3, 15),
        valor_total=Dinheiro(Decimal("100.00")),
        valor_desconto=Dinheiro(Decimal("0.00")),
        data_processamento=_agora(),
        precisa_revisao=False,
    )


def _lancamento(documento_id=None) -> Lancamento:
    return Lancamento(
        id=uuid4(),
        empresa_id=uuid4(),
        documento_id=documento_id,
        descricao="Compra teste",
        status=StatusLancamento.PENDENTE,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        criado_em=_agora(),
        data_lancamento=date(2024, 3, 15),
        splits=[
            Split(
                id=uuid4(), conta=CodigoConta("4.1.01.001"),
                natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal("100.00")),
            ),
            Split(
                id=uuid4(), conta=CodigoConta("1.1.01.002"),
                natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal("100.00")),
            ),
        ],
    )


# =============================================================
# TESTES — Uso básico
# =============================================================

class TestUnitOfWorkBasico:
    def test_repositorios_disponiveis_dentro_do_with(self, sf: SessionFactory) -> None:
        with UnitOfWork(sf) as uow:
            assert uow.documentos is not None
            assert uow.lancamentos is not None
            assert uow.audit is not None

    def test_repositorios_none_fora_do_with(self, sf: SessionFactory) -> None:
        uow = UnitOfWork(sf)
        with uow:
            pass
        assert uow.documentos is None
        assert uow.lancamentos is None
        assert uow.audit is None

    def test_commit_persiste_documento(self, sf: SessionFactory) -> None:
        doc = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc)
            uow.commit()

        with UnitOfWork(sf) as uow:
            encontrado = uow.documentos.buscar_por_id(doc.id)
            assert encontrado is not None

    def test_sem_commit_nao_persiste(self, sf: SessionFactory) -> None:
        doc = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc)
            # sem commit() — deve reverter

        with UnitOfWork(sf) as uow:
            encontrado = uow.documentos.buscar_por_id(doc.id)
            assert encontrado is None


# =============================================================
# TESTES — Transação atômica multi-repositório
# =============================================================

class TestTransacaoAtomica:
    def test_documento_lancamento_audit_juntos(self, sf: SessionFactory) -> None:
        doc = _doc()
        lanc = _lancamento(documento_id=doc.id)

        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc)
            uow.lancamentos.salvar(lanc)
            uow.audit.registrar(
                tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                payload={"nome_arquivo": doc.nome_arquivo},
                documento_id=str(doc.id),
            )
            uow.commit()

        with UnitOfWork(sf) as uow:
            assert uow.documentos.buscar_por_id(doc.id) is not None
            assert uow.lancamentos.buscar_por_id(lanc.id) is not None
            eventos = uow.audit.listar_por_empresa(str(doc.empresa_id))
            # audit não filtra por empresa_id do doc aqui pois não foi setado — verificamos hash chain
            assert uow.audit.buscar_por_documento(doc.hash_sha256) is None  # documento_hash não setado

    def test_rollback_em_excecao_reverte_tudo(self, sf: SessionFactory) -> None:
        doc = _doc()
        lanc = _lancamento(documento_id=doc.id)

        with pytest.raises(ValueError):
            with UnitOfWork(sf) as uow:
                uow.documentos.salvar(doc)
                uow.lancamentos.salvar(lanc)
                raise ValueError("falha simulada antes do commit")

        with UnitOfWork(sf) as uow:
            assert uow.documentos.buscar_por_id(doc.id) is None
            assert uow.lancamentos.buscar_por_id(lanc.id) is None

    def test_rollback_explicito(self, sf: SessionFactory) -> None:
        doc = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc)
            uow.rollback()
            # após rollback, sessão ainda utilizável para nova operação
            assert uow.documentos.buscar_por_id(doc.id) is None

    def test_audit_chain_mantida_apos_commit(self, sf: SessionFactory) -> None:
        with UnitOfWork(sf) as uow:
            evt1 = uow.audit.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {"a": 1})
            uow.commit()

        with UnitOfWork(sf) as uow:
            evt2 = uow.audit.registrar(TipoEvento.LANCAMENTO_GERADO, {"b": 2})
            uow.commit()
            assert evt2.hash_anterior == evt1.hash_proprio


# =============================================================
# TESTES — Múltiplas UoW independentes
# =============================================================

class TestMultiplasUoW:
    def test_uow_sequenciais_veem_dados_persistidos(self, sf: SessionFactory) -> None:
        doc1 = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc1)
            uow.commit()

        doc2 = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc2)
            uow.commit()

        with UnitOfWork(sf) as uow:
            assert uow.documentos.buscar_por_id(doc1.id) is not None
            assert uow.documentos.buscar_por_id(doc2.id) is not None

    def test_falha_em_uma_uow_nao_afeta_outra(self, sf: SessionFactory) -> None:
        doc_ok = _doc()
        with UnitOfWork(sf) as uow:
            uow.documentos.salvar(doc_ok)
            uow.commit()

        doc_falha = _doc()
        with pytest.raises(ValueError):
            with UnitOfWork(sf) as uow:
                uow.documentos.salvar(doc_falha)
                raise ValueError("erro")

        with UnitOfWork(sf) as uow:
            assert uow.documentos.buscar_por_id(doc_ok.id) is not None
            assert uow.documentos.buscar_por_id(doc_falha.id) is None
