"""Testes dos parsers determinísticos — Etapa 3.

Cobre: DetectorDocumento, OFXParser, parsers CSV por banco.
Meta: elevar cobertura de core/motores_* de 0% para ≥ 85%.
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from core.domain.entities import (
    Dinheiro,
    NaturezaLancamento,
    TipoDocumento,
)
from core.parsers.detector import DetectorDocumento, TipoNaoSuportadoError


# =============================================================
# FIXTURES — arquivos sintéticos para teste (sem dados reais)
# =============================================================

@pytest.fixture
def tmp_ofx(tmp_path: Path) -> Path:
    """Extrato OFX mínimo válido."""
    f = tmp_path / "extrato.ofx"
    f.write_text(
        "OFXHEADER:100\nDATA:SGML\nOFXSGML:151\n"
        "<OFX><BANKMSGSRSV1><STMTTRNRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
    )
    return f


@pytest.fixture
def tmp_csv_nubank(tmp_path: Path) -> Path:
    """CSV no formato Nubank (date,title,amount)."""
    f = tmp_path / "nubank.csv"
    f.write_text(
        "date,title,amount\n"
        "2026-06-01,Uber,25.50\n"
        "2026-06-02,iFood,42.90\n"
        "2026-06-03,Spotify,21.90\n",
        encoding="utf-8-sig",
    )
    return f


@pytest.fixture
def tmp_csv_inter(tmp_path: Path) -> Path:
    """CSV no formato Banco Inter."""
    f = tmp_path / "inter.csv"
    f.write_text(
        "Data;Tipo;Descrição;Valor\n"
        "01/06/2026;Débito;UBER VIAGEM;-25,50\n"
        "02/06/2026;Crédito;PIX RECEBIDO JOAO;150,00\n"
        "03/06/2026;Débito;SUPERMERCADO EXTRA;-87,30\n",
        encoding="utf-8-sig",
    )
    return f


@pytest.fixture
def tmp_csv_bradesco(tmp_path: Path) -> Path:
    """CSV no formato Bradesco."""
    f = tmp_path / "bradesco.csv"
    f.write_text(
        "Data;Histórico;Docto;Crédito (R$);Débito (R$);Saldo (R$)\n"
        "01/06/2026;BRADESCO;001;;25,50;1000,00\n"
        "02/06/2026;PIX RECEBIDO;002;150,00;;1150,00\n",
        encoding="latin-1",
    )
    return f


@pytest.fixture
def tmp_xml_nfe(tmp_path: Path) -> Path:
    """XML mínimo de NF-e."""
    f = tmp_path / "nfe.xml"
    f.write_text(
        '<?xml version="1.0"?>'
        '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
        '<NFe/></nfeProc>'
    )
    return f


@pytest.fixture
def tmp_xml_invalido(tmp_path: Path) -> Path:
    """XML que não é NF-e."""
    f = tmp_path / "outro.xml"
    f.write_text('<?xml version="1.0"?><root><dados>123</dados></root>')
    return f


@pytest.fixture
def tmp_pdf_texto(tmp_path: Path) -> Path:
    """Arquivo com extensão .pdf (não é PDF real, só para testar extensão)."""
    f = tmp_path / "extrato.pdf"
    f.write_bytes(b"%PDF-1.4 fake pdf content")
    return f


@pytest.fixture
def tmp_imagem(tmp_path: Path) -> Path:
    """Arquivo .jpg fictício."""
    f = tmp_path / "boleto.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    return f


# =============================================================
# DETECTOR DE DOCUMENTOS
# =============================================================

class TestDetectorDocumento:
    def test_detecta_ofx(self, tmp_ofx: Path) -> None:
        d = DetectorDocumento()
        assert d.detectar(tmp_ofx) == TipoDocumento.OFX

    def test_detecta_csv(self, tmp_csv_nubank: Path) -> None:
        d = DetectorDocumento()
        assert d.detectar(tmp_csv_nubank) == TipoDocumento.CSV

    def test_detecta_nfe_xml(self, tmp_xml_nfe: Path) -> None:
        d = DetectorDocumento()
        assert d.detectar(tmp_xml_nfe) == TipoDocumento.NFE_XML

    def test_rejeita_xml_invalido(self, tmp_xml_invalido: Path) -> None:
        d = DetectorDocumento()
        with pytest.raises(TipoNaoSuportadoError):
            d.detectar(tmp_xml_invalido)

    def test_detecta_imagem(self, tmp_imagem: Path) -> None:
        d = DetectorDocumento()
        assert d.detectar(tmp_imagem) == TipoDocumento.IMAGEM

    def test_rejeita_extensao_desconhecida(self, tmp_path: Path) -> None:
        f = tmp_path / "arquivo.xyz"
        f.write_text("dados")
        d = DetectorDocumento()
        with pytest.raises(TipoNaoSuportadoError):
            d.detectar(f)

    def test_erro_arquivo_inexistente(self, tmp_path: Path) -> None:
        d = DetectorDocumento()
        with pytest.raises(FileNotFoundError):
            d.detectar(tmp_path / "nao_existe.ofx")

    def test_hash_consistente(self, tmp_csv_nubank: Path) -> None:
        d = DetectorDocumento()
        h1 = d.calcular_hash(tmp_csv_nubank)
        h2 = d.calcular_hash(tmp_csv_nubank)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_hash_diferente_para_arquivos_distintos(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("conteudo A")
        b.write_text("conteudo B")
        d = DetectorDocumento()
        assert d.calcular_hash(a) != d.calcular_hash(b)

    def test_hash_muda_com_conteudo(self, tmp_path: Path) -> None:
        f = tmp_path / "teste.csv"
        f.write_text("versao 1")
        d = DetectorDocumento()
        h1 = d.calcular_hash(f)
        f.write_text("versao 2")
        h2 = d.calcular_hash(f)
        assert h1 != h2


# =============================================================
# PARSER CSV — NUBANK
# =============================================================

class TestParsearNubank:
    def _parsear(self, filepath: Path):
        from core.parsers.csv.nubank import parsear_nubank as _parsear_nubank
        return list(_parsear_nubank(filepath))

    def test_parseia_tres_transacoes(self, tmp_csv_nubank: Path) -> None:
        docs = self._parsear(tmp_csv_nubank)
        assert len(docs) == 3

    def test_valores_corretos(self, tmp_csv_nubank: Path) -> None:
        docs = self._parsear(tmp_csv_nubank)
        valores = [d.valor_total.valor for d in docs]
        assert Decimal("25.50") in valores
        assert Decimal("42.90") in valores
        assert Decimal("21.90") in valores

    def test_valores_sao_dinheiro(self, tmp_csv_nubank: Path) -> None:
        docs = self._parsear(tmp_csv_nubank)
        for doc in docs:
            assert isinstance(doc.valor_total, Dinheiro)
            assert isinstance(doc.valor_liquido, Dinheiro)

    def test_data_correta(self, tmp_csv_nubank: Path) -> None:
        from datetime import date
        docs = self._parsear(tmp_csv_nubank)
        assert docs[0].data_emissao == date(2026, 6, 1)

    def test_confidence_scores_sao_lista(self, tmp_csv_nubank: Path) -> None:
        from core.domain.entities import ConfidenceScore
        docs = self._parsear(tmp_csv_nubank)
        for doc in docs:
            assert isinstance(doc.confidence_scores, list)
            assert all(isinstance(s, ConfidenceScore) for s in doc.confidence_scores)

    def test_tipo_documento_csv(self, tmp_csv_nubank: Path) -> None:
        docs = self._parsear(tmp_csv_nubank)
        for doc in docs:
            assert doc.tipo == TipoDocumento.CSV

    def test_ignora_linhas_invalidas(self, tmp_path: Path) -> None:
        from core.parsers.csv.nubank import parsear_nubank as _parsear_nubank
        f = tmp_path / "nubank_ruim.csv"
        f.write_text(
            "date,title,amount\n"
            "2026-06-01,Uber,25.50\n"
            "DATA_INVALIDA,Sem data,10.00\n"
            "2026-06-03,iFood,42.90\n",
            encoding="utf-8-sig",
        )
        docs = list(_parsear_nubank(f))
        assert len(docs) == 2

    def test_debito_tem_natureza_debito(self, tmp_path: Path) -> None:
        from core.parsers.csv.nubank import parsear_nubank as _parsear_nubank
        f = tmp_path / "nubank_debito.csv"
        f.write_text(
            "date,title,amount\n"
            "2026-06-01,Uber,25.50\n",
            encoding="utf-8-sig",
        )
        docs = list(_parsear_nubank(f))
        # Nubank fatura: valor positivo = saída (débito)
        assert docs[0].natureza_operacao == NaturezaLancamento.DEBITO


# =============================================================
# PARSER CSV — BANCO INTER
# =============================================================

class TestParsearInter:
    def _parsear(self, filepath: Path):
        from core.parsers.csv.inter import parsear_inter as _parsear_inter
        return list(_parsear_inter(filepath))

    def test_parseia_tres_transacoes(self, tmp_csv_inter: Path) -> None:
        docs = self._parsear(tmp_csv_inter)
        assert len(docs) == 3

    def test_valores_absolutos(self, tmp_csv_inter: Path) -> None:
        """Valores negativos (débitos) viram positivos — sinal vai em natureza_operacao."""
        docs = self._parsear(tmp_csv_inter)
        for doc in docs:
            assert doc.valor_total.valor >= 0
            assert doc.valor_liquido.valor >= 0

    def test_pix_recebido_tem_natureza_credito(self, tmp_csv_inter: Path) -> None:
        docs = self._parsear(tmp_csv_inter)
        # Linha 2: "PIX RECEBIDO JOAO;150,00" — valor positivo = crédito
        creditos = [d for d in docs if d.natureza_operacao == NaturezaLancamento.CREDITO]
        assert len(creditos) >= 1

    def test_tipos_sao_dinheiro(self, tmp_csv_inter: Path) -> None:
        docs = self._parsear(tmp_csv_inter)
        for doc in docs:
            assert isinstance(doc.valor_total, Dinheiro)


# =============================================================
# PARSER CSV — BRADESCO
# =============================================================

class TestParsearBradesco:
    def _parsear(self, filepath: Path):
        from core.parsers.csv.bradesco import parsear_bradesco as _parsear_bradesco
        return list(_parsear_bradesco(filepath))

    def test_parseia_transacoes(self, tmp_csv_bradesco: Path) -> None:
        docs = self._parsear(tmp_csv_bradesco)
        assert len(docs) >= 1

    def test_valores_sao_dinheiro(self, tmp_csv_bradesco: Path) -> None:
        docs = self._parsear(tmp_csv_bradesco)
        for doc in docs:
            assert isinstance(doc.valor_total, Dinheiro)


# =============================================================
# DETECÇÃO DE BANCO
# =============================================================

class TestDetectarBanco:
    def test_banco_desconhecido_lanca_erro(self, tmp_path: Path) -> None:
        from core.parsers.csv import BancoNaoIdentificadoError, detectar_banco
        f = tmp_path / "desconhecido.csv"
        f.write_text("Col1;Col2;Col3\nA;B;C\n", encoding="utf-8-sig")
        with pytest.raises(BancoNaoIdentificadoError):
            detectar_banco(f)


# =============================================================
# HELPER _parse_data_br
# =============================================================

class TestParseDateBr:
    def test_formato_ddmmyyyy(self) -> None:
        from core.parsers.csv.base import parse_data_br as _parse_data_br
        from datetime import date
        assert _parse_data_br("01/06/2026") == date(2026, 6, 1)

    def test_formato_ddmmyy(self) -> None:
        from core.parsers.csv.base import parse_data_br as _parse_data_br
        from datetime import date
        assert _parse_data_br("01/06/26") == date(2026, 6, 1)

    def test_formato_iso(self) -> None:
        from core.parsers.csv.base import parse_data_br as _parse_data_br
        from datetime import date
        assert _parse_data_br("2026-06-01") == date(2026, 6, 1)

    def test_data_invalida_lanca_erro(self) -> None:
        from core.parsers.csv.base import parse_data_br as _parse_data_br
        with pytest.raises(ValueError):
            _parse_data_br("DATA_INVALIDA")
