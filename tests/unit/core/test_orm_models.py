"""Testes dos modelos ORM — A2.

Cobre: criação de tabelas, persistência e leitura de DocumentoORM,
LancamentoORM, SplitORM e AuditEventoORM via SQLite em memória.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from core.infra.db import (
    AuditEventoORM,
    DocumentoORM,
    LancamentoORM,
    SessionFactory,
    SplitORM,
)


# =============================================================
# FIXTURE
# =============================================================

@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# DocumentoORM
# =============================================================

class TestDocumentoORM:
    def _doc(self) -> DocumentoORM:
        return DocumentoORM(
            id="doc-001",
            empresa_id="emp-001",
            hash_sha256="a" * 64,
            nome_arquivo="nfe.xml",
            tipo="nfe_xml",
            fonte_extracao="xml",
            data_processamento=_agora(),
            valor_total=Decimal("100.00"),
            valor_desconto=Decimal("0.00"),
            precisa_revisao=False,
        )

    def test_persiste_e_recupera(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(self._doc())

        with sf.session() as session:
            doc = session.get(DocumentoORM, "doc-001")
            assert doc is not None
            assert doc.nome_arquivo == "nfe.xml"
            assert doc.tipo == "nfe_xml"

    def test_valor_total_decimal(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(self._doc())

        with sf.session() as session:
            doc = session.get(DocumentoORM, "doc-001")
            assert doc.valor_total == Decimal("100.00")

    def test_metadados_nfe_json(self, sf: SessionFactory) -> None:
        doc = self._doc()
        doc.metadados_nfe = {
            "chave_acesso": "35240312345678000195550010000000011000000011",
            "cfop_itens": ["5102"],
            "finalidade": 1,
        }
        with sf.session() as session:
            session.add(doc)

        with sf.session() as session:
            doc = session.get(DocumentoORM, "doc-001")
            assert doc.metadados_nfe["finalidade"] == 1
            assert "5102" in doc.metadados_nfe["cfop_itens"]

    def test_campos_opcionais_nulos(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(self._doc())

        with sf.session() as session:
            doc = session.get(DocumentoORM, "doc-001")
            assert doc.cnpj_emitente is None
            assert doc.chave_acesso is None
            assert doc.cfop is None

    def test_unique_hash_empresa(self, sf: SessionFactory) -> None:
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with sf.session() as session:
                session.add(self._doc())
                doc2 = self._doc()
                doc2.id = "doc-002"
                session.add(doc2)


# =============================================================
# LancamentoORM + SplitORM
# =============================================================

class TestLancamentoORM:
    def _lancamento(self) -> LancamentoORM:
        return LancamentoORM(
            id="lanc-001",
            empresa_id="emp-001",
            descricao="Compra de material",
            status="pendente",
            pre_aprovado=False,
            e_parcelado=False,
            criado_em=_agora(),
            data_lancamento=date(2024, 3, 15),
        )

    def _split(self, lancamento_id: str, natureza: str, conta: str) -> SplitORM:
        return SplitORM(
            id=f"split-{natureza}-{conta}",
            lancamento_id=lancamento_id,
            conta_codigo=conta,
            natureza=natureza,
            valor=Decimal("100.00"),
            moeda="BRL",
        )

    def test_persiste_lancamento(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(self._lancamento())

        with sf.session() as session:
            lanc = session.get(LancamentoORM, "lanc-001")
            assert lanc is not None
            assert lanc.descricao == "Compra de material"
            assert lanc.status == "pendente"

    def test_persiste_com_splits(self, sf: SessionFactory) -> None:
        lanc = self._lancamento()
        lanc.splits = [
            self._split("lanc-001", "debito", "4.1.01.001"),
            self._split("lanc-001", "credito", "1.1.01.002"),
        ]
        with sf.session() as session:
            session.add(lanc)

        with sf.session() as session:
            lanc = session.get(LancamentoORM, "lanc-001")
            assert len(lanc.splits) == 2

    def test_splits_natureza(self, sf: SessionFactory) -> None:
        lanc = self._lancamento()
        lanc.splits = [
            self._split("lanc-001", "debito", "4.1.01.001"),
            self._split("lanc-001", "credito", "1.1.01.002"),
        ]
        with sf.session() as session:
            session.add(lanc)

        with sf.session() as session:
            lanc = session.get(LancamentoORM, "lanc-001")
            naturezas = {s.natureza for s in lanc.splits}
            assert "debito" in naturezas
            assert "credito" in naturezas

    def test_cascade_delete_splits(self, sf: SessionFactory) -> None:
        from sqlalchemy import select
        lanc = self._lancamento()
        lanc.splits = [
            self._split("lanc-001", "debito", "4.1.01.001"),
            self._split("lanc-001", "credito", "1.1.01.002"),
        ]
        with sf.session() as session:
            session.add(lanc)

        with sf.session() as session:
            lanc = session.get(LancamentoORM, "lanc-001")
            session.delete(lanc)

        with sf.session() as session:
            splits = session.execute(
                select(SplitORM).where(SplitORM.lancamento_id == "lanc-001")
            ).scalars().all()
            assert len(splits) == 0

    def test_lancamento_vinculado_a_documento(self, sf: SessionFactory) -> None:
        doc = DocumentoORM(
            id="doc-001",
            empresa_id="emp-001",
            hash_sha256="b" * 64,
            nome_arquivo="extrato.csv",
            tipo="csv",
            fonte_extracao="csv",
            data_processamento=_agora(),
            valor_desconto=Decimal("0.00"),
            precisa_revisao=False,
        )
        lanc = self._lancamento()
        lanc.documento_id = "doc-001"

        with sf.session() as session:
            session.add(doc)
            session.add(lanc)

        with sf.session() as session:
            lanc = session.get(LancamentoORM, "lanc-001")
            assert lanc.documento_id == "doc-001"
            assert lanc.documento.nome_arquivo == "extrato.csv"


# =============================================================
# AuditEventoORM
# =============================================================

class TestAuditEventoORM:
    def _evento(self, id: str = "evt-001", hash_ant: str = "GENESIS") -> AuditEventoORM:
        hash_proprio = "c" * 64
        return AuditEventoORM(
            id=id,
            hash_proprio=hash_proprio,
            hash_anterior=hash_ant,
            tipo="DOCUMENTO_RECEBIDO",
            timestamp="2024-03-15T10:00:00Z",
            versao_sistema="0.6.1",
            payload={"nome_arquivo": "nfe.xml", "tipo": "nfe_xml"},
            usuario="teste",
            empresa_id="emp-001",
        )

    def test_persiste_evento(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(self._evento())

        with sf.session() as session:
            from sqlalchemy import select
            evt = session.execute(
                select(AuditEventoORM).where(AuditEventoORM.id == "evt-001")
            ).scalar_one()
            assert evt.tipo == "DOCUMENTO_RECEBIDO"
            assert evt.payload["nome_arquivo"] == "nfe.xml"

    def test_hash_proprio_unico(self, sf: SessionFactory) -> None:
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with sf.session() as session:
                evt1 = self._evento("evt-001")
                evt2 = self._evento("evt-002")  # mesmo hash_proprio
                session.add(evt1)
                session.add(evt2)

    def test_chain_hash_anterior(self, sf: SessionFactory) -> None:
        evt1 = self._evento("evt-001", "GENESIS")
        evt2 = AuditEventoORM(
            id="evt-002",
            hash_proprio="d" * 64,
            hash_anterior="c" * 64,  # hash_proprio do evt1
            tipo="LANCAMENTO_GERADO",
            timestamp="2024-03-15T10:01:00Z",
            versao_sistema="0.6.1",
            payload={"valor": "100.00"},
        )
        with sf.session() as session:
            session.add(evt1)
            session.add(evt2)

        with sf.session() as session:
            from sqlalchemy import select
            evts = session.execute(
                select(AuditEventoORM).order_by(AuditEventoORM.timestamp)
            ).scalars().all()
            assert evts[1].hash_anterior == evts[0].hash_proprio

    def test_payload_json_complexo(self, sf: SessionFactory) -> None:
        evt = self._evento()
        evt.payload = {
            "nome_arquivo": "nfe.xml",
            "tipo": "nfe_xml",
            "cfop_itens": ["5102", "5101"],
            "valor": "1500.00",
            "nested": {"chave": "valor"},
        }
        with sf.session() as session:
            session.add(evt)

        with sf.session() as session:
            from sqlalchemy import select
            evt = session.execute(
                select(AuditEventoORM).where(AuditEventoORM.id == "evt-001")
            ).scalar_one()
            assert evt.payload["cfop_itens"] == ["5102", "5101"]
            assert evt.payload["nested"]["chave"] == "valor"
