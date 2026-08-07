"""Testes dos repositórios — A3.

Cobre: DocumentoRepository, LancamentoRepository, AuditRepository.
Usa SQLite em memória — sem dependência de PostgreSQL.
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
from core.infra.repositories import AuditRepository, DocumentoRepository, LancamentoRepository


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


def _doc(empresa_id=None, hash_sha256=None) -> Documento:
    return Documento(
        id=uuid4(),
        empresa_id=empresa_id or uuid4(),
        hash_sha256=hash_sha256 or ("a" * 64),
        nome_arquivo="nfe.xml",
        tipo=TipoDocumento.NFE_XML,
        fonte_extracao=FonteExtracao.XML,
        data_emissao=date(2024, 3, 15),
        valor_total=Dinheiro(Decimal("100.00")),
        valor_desconto=Dinheiro(Decimal("0.00")),
        valor_liquido=Dinheiro(Decimal("100.00")),
        data_processamento=_agora(),
        precisa_revisao=False,
    )


def _lancamento(empresa_id=None, documento_id=None) -> Lancamento:
    lanc = Lancamento(
        id=uuid4(),
        empresa_id=empresa_id or uuid4(),
        documento_id=documento_id,
        descricao="Compra de material",
        status=StatusLancamento.PENDENTE,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        pre_aprovado=True,
        criado_em=_agora(),
        data_lancamento=date(2024, 3, 15),
        splits=[
            Split(
                id=uuid4(),
                conta=CodigoConta("4.1.01.001"),
                natureza=NaturezaLancamento.DEBITO,
                valor=Dinheiro(Decimal("100.00")),
            ),
            Split(
                id=uuid4(),
                conta=CodigoConta("1.1.01.002"),
                natureza=NaturezaLancamento.CREDITO,
                valor=Dinheiro(Decimal("100.00")),
            ),
        ],
    )
    return lanc


# =============================================================
# DocumentoRepository
# =============================================================

class TestDocumentoRepository:
    def test_salvar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        doc = _doc()
        with sf.session() as session:
            repo = DocumentoRepository(session)
            repo.salvar(doc)

        with sf.session() as session:
            repo = DocumentoRepository(session)
            encontrado = repo.buscar_por_id(doc.id)
            assert encontrado is not None
            assert encontrado.nome_arquivo == "nfe.xml"
            assert encontrado.tipo == TipoDocumento.NFE_XML

    def test_buscar_por_hash(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        doc = _doc(empresa_id=empresa_id, hash_sha256="b" * 64)
        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        with sf.session() as session:
            encontrado = DocumentoRepository(session).buscar_por_hash("b" * 64, empresa_id)
            assert encontrado is not None
            assert encontrado.id == doc.id

    def test_buscar_por_hash_empresa_errada(self, sf: SessionFactory) -> None:
        doc = _doc(hash_sha256="c" * 64)
        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        with sf.session() as session:
            encontrado = DocumentoRepository(session).buscar_por_hash("c" * 64, uuid4())
            assert encontrado is None

    def test_existe_hash(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        doc = _doc(empresa_id=empresa_id, hash_sha256="d" * 64)
        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        with sf.session() as session:
            assert DocumentoRepository(session).existe_hash("d" * 64, empresa_id) is True
            assert DocumentoRepository(session).existe_hash("e" * 64, empresa_id) is False

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        doc1 = _doc(empresa_id=empresa_id, hash_sha256="f" * 64)
        doc2 = _doc(empresa_id=empresa_id, hash_sha256="g" * 64)
        doc_outro = _doc(hash_sha256="h" * 64)

        with sf.session() as session:
            repo = DocumentoRepository(session)
            repo.salvar(doc1)
            repo.salvar(doc2)
            repo.salvar(doc_outro)

        with sf.session() as session:
            lista = DocumentoRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_buscar_inexistente_retorna_none(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            assert DocumentoRepository(session).buscar_por_id(uuid4()) is None

    def test_deletar(self, sf: SessionFactory) -> None:
        doc = _doc()
        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        with sf.session() as session:
            assert DocumentoRepository(session).deletar(doc.id) is True

        with sf.session() as session:
            assert DocumentoRepository(session).buscar_por_id(doc.id) is None

    def test_deletar_inexistente_retorna_false(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            assert DocumentoRepository(session).deletar(uuid4()) is False

    def test_valor_total_preservado(self, sf: SessionFactory) -> None:
        doc = _doc()
        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        with sf.session() as session:
            encontrado = DocumentoRepository(session).buscar_por_id(doc.id)
            assert encontrado.valor_total.valor == Decimal("100.00")


# =============================================================
# LancamentoRepository
# =============================================================

class TestLancamentoRepository:
    def test_salvar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        lanc = _lancamento()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            encontrado = LancamentoRepository(session).buscar_por_id(lanc.id)
            assert encontrado is not None
            assert encontrado.descricao == "Compra de material"

    def test_splits_persistidos(self, sf: SessionFactory) -> None:
        lanc = _lancamento()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            encontrado = LancamentoRepository(session).buscar_por_id(lanc.id)
            assert len(encontrado.splits) == 2
            naturezas = {s.natureza for s in encontrado.splits}
            assert NaturezaLancamento.DEBITO in naturezas
            assert NaturezaLancamento.CREDITO in naturezas

    def test_listar_por_documento(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        doc = _doc(empresa_id=empresa_id)

        with sf.session() as session:
            DocumentoRepository(session).salvar(doc)

        lanc = _lancamento(empresa_id=empresa_id, documento_id=doc.id)
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            lista = LancamentoRepository(session).listar_por_documento(doc.id)
            assert len(lista) == 1
            assert lista[0].id == lanc.id

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        lanc1 = _lancamento(empresa_id=empresa_id)
        lanc2 = _lancamento(empresa_id=empresa_id)
        lanc_outro = _lancamento()

        with sf.session() as session:
            repo = LancamentoRepository(session)
            repo.salvar(lanc1)
            repo.salvar(lanc2)
            repo.salvar(lanc_outro)

        with sf.session() as session:
            lista = LancamentoRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_status_preservado(self, sf: SessionFactory) -> None:
        lanc = _lancamento()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            encontrado = LancamentoRepository(session).buscar_por_id(lanc.id)
            assert encontrado.status == StatusLancamento.PENDENTE

    def test_deletar(self, sf: SessionFactory) -> None:
        lanc = _lancamento()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            assert LancamentoRepository(session).deletar(lanc.id) is True

        with sf.session() as session:
            assert LancamentoRepository(session).buscar_por_id(lanc.id) is None

    def test_valor_split_preservado(self, sf: SessionFactory) -> None:
        lanc = _lancamento()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            encontrado = LancamentoRepository(session).buscar_por_id(lanc.id)
            debito = next(s for s in encontrado.splits if s.natureza == NaturezaLancamento.DEBITO)
            assert debito.valor.valor == Decimal("100.00")


# =============================================================
# AuditRepository
# =============================================================

class TestAuditRepository:
    def test_registrar_evento(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = AuditRepository(session)
            evento = repo.registrar(
                tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                payload={"nome_arquivo": "nfe.xml"},
                usuario="teste",
                empresa_id="emp-001",
            )
            assert evento.hash_proprio != ""
            assert evento.hash_anterior == "GENESIS"

    def test_chain_hash(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = AuditRepository(session)
            evt1 = repo.registrar(
                tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                payload={"nome_arquivo": "nfe.xml"},
            )
            evt2 = repo.registrar(
                tipo=TipoEvento.LANCAMENTO_GERADO,
                payload={"valor": "100.00"},
            )
            assert evt2.hash_anterior == evt1.hash_proprio

    def test_buscar_por_documento(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = AuditRepository(session)
            repo.registrar(
                tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                payload={"nome_arquivo": "nfe.xml"},
                documento_hash="abc123",
            )

        with sf.session() as session:
            resultado = AuditRepository(session).buscar_por_documento("abc123")
            assert resultado is not None
            assert "timestamp" in resultado

    def test_buscar_documento_inexistente(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            assert AuditRepository(session).buscar_por_documento("nao_existe") is None

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = AuditRepository(session)
            repo.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {}, empresa_id="emp-A")
            repo.registrar(TipoEvento.LANCAMENTO_GERADO, {}, empresa_id="emp-A")
            repo.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {}, empresa_id="emp-B")

        with sf.session() as session:
            lista = AuditRepository(session).listar_por_empresa("emp-A")
            assert len(lista) == 2

    def test_verificar_integridade(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = AuditRepository(session)
            repo.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {"a": 1})
            repo.registrar(TipoEvento.LANCAMENTO_GERADO, {"b": 2})

        with sf.session() as session:
            ok, erros = AuditRepository(session).verificar_integridade()
            assert ok is True
            assert erros == []

    def test_chain_entre_sessoes(self, sf: SessionFactory) -> None:
        """Hash chain mantida corretamente entre sessões distintas."""
        with sf.session() as session:
            repo = AuditRepository(session)
            evt1 = repo.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {"s": 1})

        with sf.session() as session:
            repo = AuditRepository(session)
            evt2 = repo.registrar(TipoEvento.LANCAMENTO_GERADO, {"s": 2})
            assert evt2.hash_anterior == evt1.hash_proprio
