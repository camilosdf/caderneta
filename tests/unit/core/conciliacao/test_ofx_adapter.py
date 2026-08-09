"""Testes do OFXBankStatementAdapter — Etapa 8.3.

Herméticos: OFX gerado inline (sem arquivo externo, sem rede).
Cobre: importar(), detectar_conta(), idempotência, Protocol,
       campos críticos (FITID, valor, data, natureza).
"""

import textwrap
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from core.adapters.ofx_bank_statement import OFXBankStatementAdapter
from core.domain.entities import NaturezaLancamento, OrigemExtrato
from core.ports.bank_statement import BankStatementPort

# =============================================================
# FIXTURE: OFX MÍNIMO VÁLIDO
# =============================================================

OFX_MINIMO = textwrap.dedent("""\
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
    <TRNAMT>-100.00</TRNAMT>
    <FITID>TX001</FITID>
    <MEMO>UBER DO BRASIL</MEMO>
    </STMTTRN>
    <STMTTRN>
    <TRNTYPE>CREDIT</TRNTYPE>
    <DTPOSTED>20260720</DTPOSTED>
    <TRNAMT>2500.00</TRNAMT>
    <FITID>TX002</FITID>
    <MEMO>SALARIO EMPRESA</MEMO>
    </STMTTRN>
    <STMTTRN>
    <TRNTYPE>DEBIT</TRNTYPE>
    <DTPOSTED>20260722</DTPOSTED>
    <TRNAMT>-50.00</TRNAMT>
    <FITID>TX003</FITID>
    <MEMO>IFOOD PEDIDO</MEMO>
    </STMTTRN>
    </BANKTRANLIST>
    <LEDGERBAL>
    <BALAMT>1000.00</BALAMT>
    <DTASOF>20260731</DTASOF>
    </LEDGERBAL>
    </STMTRS>
    </STMTTRNRS>
    </BANKMSGSRSV1>
    </OFX>
""")


@pytest.fixture
def ofx_file(tmp_path: Path) -> Path:
    """Arquivo OFX temporário com 3 transações."""
    arquivo = tmp_path / "extrato_julho.ofx"
    arquivo.write_text(OFX_MINIMO, encoding="utf-8")
    return arquivo


@pytest.fixture
def adapter() -> OFXBankStatementAdapter:
    return OFXBankStatementAdapter()


EMPRESA_ID = uuid4()
IMPORT_ID = str(uuid4())


# =============================================================
# CONTRATO
# =============================================================

class TestContratoAdapter:
    def test_satisfaz_bank_statement_port(self, adapter) -> None:
        assert isinstance(adapter, BankStatementPort)


# =============================================================
# IMPORTAÇÃO
# =============================================================

class TestImportar:
    def test_retorna_lista_de_transacoes(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        assert isinstance(txs, list)
        assert len(txs) == 3

    def test_fitid_preservado(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        fitids = {tx.fitid for tx in txs}
        assert "TX001" in fitids
        assert "TX002" in fitids
        assert "TX003" in fitids

    def test_valor_sempre_positivo(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        assert all(tx.valor.valor > 0 for tx in txs)

    def test_natureza_debito_para_valor_negativo(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        tx001 = next(tx for tx in txs if tx.fitid == "TX001")
        assert tx001.natureza == NaturezaLancamento.DEBITO
        assert tx001.valor.valor == Decimal("100.00")

    def test_natureza_credito_para_valor_positivo(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        tx002 = next(tx for tx in txs if tx.fitid == "TX002")
        assert tx002.natureza == NaturezaLancamento.CREDITO
        assert tx002.valor.valor == Decimal("2500.00")

    def test_descricao_em_maiusculas(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        tx001 = next(tx for tx in txs if tx.fitid == "TX001")
        assert tx001.descricao == tx001.descricao.upper()
        assert "UBER" in tx001.descricao

    def test_empresa_id_propagado(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        assert all(tx.empresa_id == EMPRESA_ID for tx in txs)

    def test_id_importacao_propagado(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        assert all(tx.id_importacao == IMPORT_ID for tx in txs)

    def test_origem_ofx(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        assert all(tx.origem == OrigemExtrato.OFX for tx in txs)

    def test_conta_bancaria_extraida(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        conta = txs[0].conta_bancaria
        assert conta.numero_conta == "12345-6"

    def test_data_correta(self, adapter, ofx_file) -> None:
        from datetime import date
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        tx001 = next(tx for tx in txs if tx.fitid == "TX001")
        assert tx001.data == date(2026, 7, 15)


# =============================================================
# IDEMPOTÊNCIA
# =============================================================

class TestIdempotencia:
    def test_mesma_importacao_chaves_identicas(self, adapter, ofx_file) -> None:
        """Importar o mesmo arquivo duas vezes deve gerar as mesmas chaves."""
        txs1 = adapter.importar(ofx_file, EMPRESA_ID, "import_1")
        txs2 = adapter.importar(ofx_file, EMPRESA_ID, "import_2")

        chaves1 = {tx.chave_idempotencia() for tx in txs1}
        chaves2 = {tx.chave_idempotencia() for tx in txs2}

        assert chaves1 == chaves2

    def test_fitid_diferente_chave_diferente(self, adapter, ofx_file) -> None:
        txs = adapter.importar(ofx_file, EMPRESA_ID, IMPORT_ID)
        chaves = [tx.chave_idempotencia() for tx in txs]
        assert len(chaves) == len(set(chaves))  # todas únicas


# =============================================================
# DETECTAR CONTA
# =============================================================

class TestDetectarConta:
    def test_detecta_numero_conta(self, adapter, ofx_file) -> None:
        conta = adapter.detectar_conta(ofx_file)
        assert conta is not None
        assert "12345-6" in conta.numero_conta

    def test_arquivo_invalido_retorna_none(self, adapter, tmp_path) -> None:
        arquivo = tmp_path / "invalido.ofx"
        arquivo.write_text("nao e ofx valido")
        conta = adapter.detectar_conta(arquivo)
        assert conta is None
