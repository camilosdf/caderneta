"""Testes da ParserFactory e adaptadores de parser.

Cobre: resolução de tipo → parser, Protocol, extensibilidade,
integração NFeParser/CSVParser com fixtures reais.
"""

from pathlib import Path

import pytest

from core.domain.entities import Documento, TipoDocumento
from core.parsers.adapters import CSVParser, NFeParser, ParserProtocol
from core.parsers.ofx import OFXParser
from core.pipeline.parser_factory import ParserFactory, ParserNaoSuportadoError


# =============================================================
# FIXTURES
# =============================================================

NF_NS = "http://www.portalfiscal.inf.br/nfe"


@pytest.fixture
def nfe_xml(tmp_path: Path) -> Path:
    f = tmp_path / "nfe.xml"
    f.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<nfeProc xmlns="{NF_NS}">'
        f'<NFe><infNFe Id="NFe35240312345678000195550010000000011000000011">'
        f'<ide><nNF>1</nNF><natOp>Venda</natOp><finNFe>1</finNFe>'
        f'<dhEmi>2024-03-15T10:00:00-03:00</dhEmi></ide>'
        f'<emit><CNPJ>12345678000195</CNPJ><xNome>EMIT</xNome></emit>'
        f'<total><ICMSTot>'
        f'<vProd>100.00</vProd><vDesc>0.00</vDesc><vICMS>18.00</vICMS>'
        f'<vIPI>0.00</vIPI><vPIS>1.65</vPIS><vCOFINS>7.60</vCOFINS>'
        f'<vFrete>0.00</vFrete><vNF>100.00</vNF>'
        f'</ICMSTot></total>'
        f'</infNFe></NFe></nfeProc>',
        encoding="utf-8",
    )
    return f


@pytest.fixture
def csv_nubank(tmp_path: Path) -> Path:
    f = tmp_path / "nubank.csv"
    f.write_text(
        "date,title,amount\n"
        "2026-06-01,Uber,25.50\n"
        "2026-06-02,iFood,42.90\n",
        encoding="utf-8-sig",
    )
    return f


# =============================================================
# PROTOCOL
# =============================================================

class TestParserProtocol:
    def test_nfe_parser_satisfaz_protocol(self) -> None:
        assert isinstance(NFeParser(), ParserProtocol)

    def test_csv_parser_satisfaz_protocol(self) -> None:
        assert isinstance(CSVParser(), ParserProtocol)

    def test_ofx_parser_satisfaz_protocol(self) -> None:
        assert isinstance(OFXParser(), ParserProtocol)


# =============================================================
# PARSER FACTORY
# =============================================================

class TestParserFactory:
    def test_resolve_nfe(self) -> None:
        f = ParserFactory()
        parser = f.obter(TipoDocumento.NFE_XML)
        assert isinstance(parser, NFeParser)

    def test_resolve_ofx(self) -> None:
        f = ParserFactory()
        parser = f.obter(TipoDocumento.OFX)
        assert isinstance(parser, OFXParser)

    def test_resolve_csv(self) -> None:
        f = ParserFactory()
        parser = f.obter(TipoDocumento.CSV)
        assert isinstance(parser, CSVParser)

    def test_tipo_nao_suportado_lanca_erro(self) -> None:
        f = ParserFactory()
        with pytest.raises(ParserNaoSuportadoError):
            f.obter(TipoDocumento.PDF_TEXTO)

    def test_tipos_suportados(self) -> None:
        f = ParserFactory()
        assert TipoDocumento.NFE_XML in f.tipos_suportados
        assert TipoDocumento.OFX in f.tipos_suportados
        assert TipoDocumento.CSV in f.tipos_suportados

    def test_registrar_novo_parser(self) -> None:
        """Extensibilidade: registrar tipo sem alterar o use case."""
        class FakeParser:
            def parsear(self, filepath):
                return iter([])

        f = ParserFactory()
        f.registrar(TipoDocumento.PDF_TEXTO, FakeParser())
        parser = f.obter(TipoDocumento.PDF_TEXTO)
        assert isinstance(parser, FakeParser)

    def test_substituir_parser_existente(self) -> None:
        class MockNFe:
            def parsear(self, filepath):
                return iter([])

        f = ParserFactory()
        f.registrar(TipoDocumento.NFE_XML, MockNFe())
        assert isinstance(f.obter(TipoDocumento.NFE_XML), MockNFe)


# =============================================================
# NFeParser — integração
# =============================================================

class TestNFeParser:
    def test_retorna_iterator(self, nfe_xml: Path) -> None:
        from collections.abc import Iterator
        parser = NFeParser()
        resultado = parser.parsear(nfe_xml)
        assert hasattr(resultado, "__iter__")

    def test_gera_um_documento(self, nfe_xml: Path) -> None:
        parser = NFeParser()
        docs = list(parser.parsear(nfe_xml))
        assert len(docs) == 1

    def test_documento_e_instancia_correta(self, nfe_xml: Path) -> None:
        parser = NFeParser()
        docs = list(parser.parsear(nfe_xml))
        assert isinstance(docs[0], Documento)

    def test_tipo_nfe_xml(self, nfe_xml: Path) -> None:
        parser = NFeParser()
        docs = list(parser.parsear(nfe_xml))
        assert docs[0].tipo == TipoDocumento.NFE_XML

    def test_metadados_nfe_presentes(self, nfe_xml: Path) -> None:
        parser = NFeParser()
        docs = list(parser.parsear(nfe_xml))
        assert docs[0].metadados_nfe is not None


# =============================================================
# CSVParser — integração
# =============================================================

class TestCSVParser:
    def test_retorna_iterator(self, csv_nubank: Path) -> None:
        parser = CSVParser()
        resultado = parser.parsear(csv_nubank)
        assert hasattr(resultado, "__iter__")

    def test_gera_dois_documentos(self, csv_nubank: Path) -> None:
        parser = CSVParser()
        docs = list(parser.parsear(csv_nubank))
        assert len(docs) == 2

    def test_documentos_sao_instancias_corretas(self, csv_nubank: Path) -> None:
        parser = CSVParser()
        docs = list(parser.parsear(csv_nubank))
        assert all(isinstance(d, Documento) for d in docs)

    def test_tipo_csv(self, csv_nubank: Path) -> None:
        parser = CSVParser()
        docs = list(parser.parsear(csv_nubank))
        assert all(d.tipo == TipoDocumento.CSV for d in docs)


# =============================================================
# FACTORY + PARSERS — integração via obter()
# =============================================================

class TestFactoryIntegracao:
    def test_factory_nfe_parseia_arquivo(self, nfe_xml: Path) -> None:
        f = ParserFactory()
        parser = f.obter(TipoDocumento.NFE_XML)
        docs = list(parser.parsear(nfe_xml))
        assert len(docs) == 1
        assert docs[0].tipo == TipoDocumento.NFE_XML

    def test_factory_csv_parseia_arquivo(self, csv_nubank: Path) -> None:
        f = ParserFactory()
        parser = f.obter(TipoDocumento.CSV)
        docs = list(parser.parsear(csv_nubank))
        assert len(docs) == 2
        assert all(d.tipo == TipoDocumento.CSV for d in docs)
