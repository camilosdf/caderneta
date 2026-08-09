"""Testes do TransacaoBancariaRepository e integração Etapa 8.4.

Herméticos: SQLite em memória, sem arquivo OFX, sem CLI real.
Cobre: idempotência de importação, persistência, listagem por período,
e integração completa OFXAdapter → Repository → MotorConciliacao.
"""

import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from core.adapters.ofx_bank_statement import OFXBankStatementAdapter
from core.domain.entities import (
    ContaBancaria,
    Dinheiro,
    Lancamento,
    MetodoMatching,
    NaturezaLancamento,
    NivelAprovacao,
    CodigoConta,
    Split,
    StatusLancamento,
    TipoConciliacao,
    TransacaoBancaria,
)
from core.infra.db import SessionFactory
from core.infra.repositories import TransacaoBancariaRepository
from core.rule_engine.motor_conciliacao import MotorConciliacao, ToleranciasConciliacao

EMPRESA_ID = uuid4()
IMPORT_ID = str(uuid4())


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


def _conta() -> ContaBancaria:
    return ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6")


def _tx(fitid: str = "TX001", valor: str = "100.00", data: date = date(2026, 7, 15)) -> TransacaoBancaria:
    return TransacaoBancaria(
        empresa_id=EMPRESA_ID,
        conta_bancaria=_conta(),
        fitid=fitid,
        data=data,
        valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO,
        descricao="UBER DO BRASIL",
        id_importacao=IMPORT_ID,
    )


def _lanc(valor: str = "100.00", data: date = date(2026, 7, 15)) -> Lancamento:
    return Lancamento(
        empresa_id=EMPRESA_ID,
        descricao="UBER DO BRASIL",
        status=StatusLancamento.APROVADO,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=data,
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal(valor))),
        ],
    )


# =============================================================
# REPOSITÓRIO
# =============================================================

class TestTransacaoBancariaRepository:
    def test_salvar_nova_retorna_true(self, sf) -> None:
        tx = _tx()
        with sf.session() as session:
            repo = TransacaoBancariaRepository(session)
            resultado = repo.salvar_se_nova(tx)
        assert resultado is True

    def test_salvar_mesma_fitid_retorna_false(self, sf) -> None:
        tx = _tx(fitid="TX001")
        with sf.session() as session:
            TransacaoBancariaRepository(session).salvar_se_nova(tx)

        tx2 = _tx(fitid="TX001")  # mesma chave
        with sf.session() as session:
            resultado = TransacaoBancariaRepository(session).salvar_se_nova(tx2)

        assert resultado is False  # idempotente

    def test_fitid_diferente_aceita(self, sf) -> None:
        with sf.session() as s:
            TransacaoBancariaRepository(s).salvar_se_nova(_tx(fitid="TX001"))
        with sf.session() as s:
            resultado = TransacaoBancariaRepository(s).salvar_se_nova(_tx(fitid="TX002"))
        assert resultado is True

    def test_listar_por_periodo(self, sf) -> None:
        with sf.session() as s:
            repo = TransacaoBancariaRepository(s)
            repo.salvar_se_nova(_tx(fitid="TX_JUL", data=date(2026, 7, 15)))
            repo.salvar_se_nova(_tx(fitid="TX_AGO", data=date(2026, 8, 10)))

        with sf.session() as s:
            txs = TransacaoBancariaRepository(s).listar_por_empresa_e_periodo(
                EMPRESA_ID, date(2026, 7, 1), date(2026, 7, 31)
            )

        assert len(txs) == 1
        assert txs[0].fitid == "TX_JUL"

    def test_isolamento_por_empresa(self, sf) -> None:
        outra_empresa = uuid4()
        tx_minha = _tx(fitid="TX_MINHA")
        tx_outra = TransacaoBancaria(
            empresa_id=outra_empresa,
            conta_bancaria=_conta(),
            fitid="TX_OUTRA",
            data=date(2026, 7, 15),
            valor=Dinheiro(Decimal("100.00")),
            natureza=NaturezaLancamento.DEBITO,
        )
        with sf.session() as s:
            repo = TransacaoBancariaRepository(s)
            repo.salvar_se_nova(tx_minha)
            repo.salvar_se_nova(tx_outra)

        with sf.session() as s:
            txs = TransacaoBancariaRepository(s).listar_por_empresa_e_periodo(
                EMPRESA_ID, date(2026, 7, 1), date(2026, 7, 31)
            )

        assert len(txs) == 1
        assert txs[0].fitid == "TX_MINHA"

    def test_dados_persistidos_corretamente(self, sf) -> None:
        tx = _tx(fitid="TX_DADOS", valor="250.50")
        with sf.session() as s:
            TransacaoBancariaRepository(s).salvar_se_nova(tx)

        with sf.session() as s:
            txs = TransacaoBancariaRepository(s).listar_por_empresa_e_periodo(
                EMPRESA_ID, date(2026, 7, 1), date(2026, 7, 31)
            )

        assert txs[0].valor.valor == Decimal("250.50")
        assert txs[0].natureza == NaturezaLancamento.DEBITO
        assert txs[0].fitid == "TX_DADOS"


# =============================================================
# INTEGRAÇÃO: OFXAdapter → Repository → MotorConciliacao
# =============================================================

OFX_TESTE = textwrap.dedent("""\
    OFXHEADER:100
    DATA:OFXSGML
    VERSION:102
    SECURITY:NONE
    ENCODING:USASCII
    CHARSET:1252
    COMPRESSION:NONE
    OLDFILEUID:NONE
    NEWFILEUID:NONE

    <OFX>
    <SIGNONMSGSRSV1>
    <SONRS>
    <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
    <DTSERVER>20260715120000</DTSERVER>
    <LANGUAGE>POR</LANGUAGE>
    </SONRS>
    </SIGNONMSGSRSV1>
    <BANKMSGSRSV1>
    <STMTTRNRS>
    <TRNUID>1</TRNUID>
    <STMTRS>
    <CURDEF>BRL</CURDEF>
    <BANKACCTFROM>
    <BANKID>341</BANKID>
    <ACCTID>12345-6</ACCTID>
    <ACCTTYPE>CHECKING</ACCTTYPE>
    </BANKACCTFROM>
    <BANKTRANLIST>
    <DTSTART>20260701</DTSTART>
    <DTEND>20260731</DTEND>
    <STMTTRN>
    <TRNTYPE>DEBIT</TRNTYPE>
    <DTPOSTED>20260715</DTPOSTED>
    <TRNAMT>-150.00</TRNAMT>
    <FITID>INTEG_TX001</FITID>
    <MEMO>SUPERMERCADO ABC</MEMO>
    </STMTTRN>
    <STMTTRN>
    <TRNTYPE>DEBIT</TRNTYPE>
    <DTPOSTED>20260720</DTPOSTED>
    <TRNAMT>-500.00</TRNAMT>
    <FITID>INTEG_TX002</FITID>
    <MEMO>SEM LANCAMENTO CORRESPONDENTE</MEMO>
    </STMTTRN>
    </BANKTRANLIST>
    <LEDGERBAL>
    <BALAMT>5000.00</BALAMT>
    <DTASOF>20260731</DTASOF>
    </LEDGERBAL>
    </STMTRS>
    </STMTTRNRS>
    </BANKMSGSRSV1>
    </OFX>
""")


class TestIntegracaoCompleta:
    def test_fluxo_importar_conciliar(self, sf, tmp_path) -> None:
        """Fluxo completo: OFX → banco → motor → relatório."""
        # 1. Criar arquivo OFX
        ofx_path = tmp_path / "extrato.ofx"
        ofx_path.write_text(OFX_TESTE, encoding="utf-8")

        # 2. Importar
        adapter = OFXBankStatementAdapter()
        transacoes = adapter.importar(ofx_path, EMPRESA_ID, IMPORT_ID)
        with sf.session() as s:
            repo = TransacaoBancariaRepository(s)
            for tx in transacoes:
                repo.salvar_se_nova(tx)

        # 3. Preparar lançamento que bate com INTEG_TX001
        lanc = _lanc(valor="150.00", data=date(2026, 7, 15))
        lanc.descricao = "SUPERMERCADO ABC"

        # 4. Conciliar
        with sf.session() as s:
            txs_banco = TransacaoBancariaRepository(s).listar_por_empresa_e_periodo(
                EMPRESA_ID, date(2026, 7, 1), date(2026, 7, 31)
            )

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc],
            transacoes=txs_banco,
            empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 7, 1),
            periodo_fim=date(2026, 7, 31),
        )

        # 5. Verificar
        assert len(relatorio.conciliados) >= 1
        assert len(relatorio.sem_documento) >= 1  # INTEG_TX002 sem lançamento

    def test_reimportacao_idempotente(self, sf, tmp_path) -> None:
        """Reimportar o mesmo OFX não cria duplicatas."""
        ofx_path = tmp_path / "extrato.ofx"
        ofx_path.write_text(OFX_TESTE, encoding="utf-8")

        adapter = OFXBankStatementAdapter()

        # Primeira importação
        txs = adapter.importar(ofx_path, EMPRESA_ID, "import_1")
        with sf.session() as s:
            repo = TransacaoBancariaRepository(s)
            inseridas_1 = sum(1 for tx in txs if repo.salvar_se_nova(tx))

        # Segunda importação do mesmo arquivo
        txs = adapter.importar(ofx_path, EMPRESA_ID, "import_2")
        with sf.session() as s:
            repo = TransacaoBancariaRepository(s)
            inseridas_2 = sum(1 for tx in txs if repo.salvar_se_nova(tx))

        assert inseridas_1 == 2
        assert inseridas_2 == 0  # todas já existiam
