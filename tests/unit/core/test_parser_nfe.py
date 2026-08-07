"""Testes do parser NF-e XML — Etapa 3.

Cobre: extração de campos fiscais, MetadadosNFe, natureza por CFOP,
revisão automática, casos de borda (XML mínimo, campos ausentes).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.domain.entities import (
    Dinheiro,
    MetadadosNFe,
    NaturezaLancamento,
    TipoDocumento,
)
from core.parsers.nfe.xml import NFeInvalidaError, parsear_nfe


# =============================================================
# FIXTURES
# =============================================================

NF_NS = "http://www.portalfiscal.inf.br/nfe"


def _nfe_xml(
    chave: str = "35240312345678000195550010000000011000000011",
    nat_op: str = "Venda de mercadoria",
    finalidade: int = 1,
    cnpj_emit: str = "12345678000195",
    nome_emit: str = "EMPRESA TESTE LTDA",
    cnpj_dest: str = "98765432000198",
    data: str = "2024-03-15",
    valor_nf: str = "100.00",
    valor_desc: str = "5.00",
    valor_icms: str = "18.00",
    valor_pis: str = "1.65",
    valor_cofins: str = "7.60",
    valor_ipi: str = "0.00",
    cfop: str = "5102",
    ncm: str = "84713012",
    cst: str = "00",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="{NF_NS}">
  <NFe>
    <infNFe Id="NFe{chave}">
      <ide>
        <nNF>1</nNF>
        <natOp>{nat_op}</natOp>
        <finNFe>{finalidade}</finNFe>
        <dhEmi>{data}T10:00:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>{cnpj_emit}</CNPJ>
        <xNome>{nome_emit}</xNome>
      </emit>
      <dest>
        <CNPJ>{cnpj_dest}</CNPJ>
      </dest>
      <det nItem="1">
        <prod>
          <CFOP>{cfop}</CFOP>
          <NCM>{ncm}</NCM>
        </prod>
        <imposto>
          <ICMS>
            <ICMS00>
              <CST>{cst}</CST>
            </ICMS00>
          </ICMS>
        </imposto>
      </det>
      <total>
        <ICMSTot>
          <vProd>{valor_nf}</vProd>
          <vDesc>{valor_desc}</vDesc>
          <vICMS>{valor_icms}</vICMS>
          <vIPI>{valor_ipi}</vIPI>
          <vPIS>{valor_pis}</vPIS>
          <vCOFINS>{valor_cofins}</vCOFINS>
          <vFrete>0.00</vFrete>
          <vNF>{valor_nf}</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>"""


@pytest.fixture
def nfe_saida(tmp_path: Path) -> Path:
    f = tmp_path / "nfe_saida.xml"
    f.write_text(_nfe_xml(), encoding="utf-8")
    return f


@pytest.fixture
def nfe_entrada(tmp_path: Path) -> Path:
    f = tmp_path / "nfe_entrada.xml"
    f.write_text(_nfe_xml(cfop="1102", nat_op="Compra de mercadoria"), encoding="utf-8")
    return f


@pytest.fixture
def nfe_devolucao(tmp_path: Path) -> Path:
    f = tmp_path / "nfe_dev.xml"
    f.write_text(_nfe_xml(finalidade=4, nat_op="Devolução de venda"), encoding="utf-8")
    return f


@pytest.fixture
def nfe_multiplos_itens(tmp_path: Path) -> Path:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="{NF_NS}">
  <NFe>
    <infNFe Id="NFe35240312345678000195550010000000021000000021">
      <ide>
        <nNF>2</nNF>
        <natOp>Venda mista</natOp>
        <finNFe>1</finNFe>
        <dhEmi>2024-04-01T09:00:00-03:00</dhEmi>
      </ide>
      <emit><CNPJ>12345678000195</CNPJ><xNome>EMIT</xNome></emit>
      <dest><CNPJ>98765432000198</CNPJ></dest>
      <det nItem="1">
        <prod><CFOP>5102</CFOP><NCM>84713012</NCM></prod>
        <imposto><ICMS><ICMS00><CST>00</CST></ICMS00></ICMS></imposto>
      </det>
      <det nItem="2">
        <prod><CFOP>5102</CFOP><NCM>85171231</NCM></prod>
        <imposto><ICMS><ICMS00><CST>00</CST></ICMS00></ICMS></imposto>
      </det>
      <det nItem="3">
        <prod><CFOP>5101</CFOP><NCM>84713012</NCM></prod>
        <imposto><ICMS><ICMS00><CST>20</CST></ICMS00></ICMS></imposto>
      </det>
      <total>
        <ICMSTot>
          <vProd>300.00</vProd><vDesc>0.00</vDesc>
          <vICMS>54.00</vICMS><vIPI>0.00</vIPI>
          <vPIS>4.95</vPIS><vCOFINS>22.80</vCOFINS>
          <vFrete>0.00</vFrete><vNF>300.00</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>"""
    f = tmp_path / "nfe_multi.xml"
    f.write_text(xml, encoding="utf-8")
    return f


@pytest.fixture
def nfe_sem_chave(tmp_path: Path) -> Path:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="{NF_NS}">
  <NFe>
    <infNFe>
      <ide><nNF>1</nNF><natOp>Venda</natOp><finNFe>1</finNFe><dhEmi>2024-03-15</dhEmi></ide>
      <emit><CNPJ>12345678000195</CNPJ><xNome>EMIT</xNome></emit>
      <total><ICMSTot>
        <vProd>0.00</vProd><vDesc>0.00</vDesc><vICMS>0.00</vICMS>
        <vIPI>0.00</vIPI><vPIS>0.00</vPIS><vCOFINS>0.00</vCOFINS>
        <vFrete>0.00</vFrete><vNF>0.00</vNF>
      </ICMSTot></total>
    </infNFe>
  </NFe>
</nfeProc>"""
    f = tmp_path / "nfe_sem_chave.xml"
    f.write_text(xml, encoding="utf-8")
    return f


# =============================================================
# TESTES — DOCUMENTO BASE
# =============================================================

class TestParsearNFe:
    def test_tipo_documento_nfe(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.tipo == TipoDocumento.NFE_XML

    def test_data_emissao(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.data_emissao == date(2024, 3, 15)

    def test_valor_total_e_dinheiro(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert isinstance(doc.valor_total, Dinheiro)
        assert doc.valor_total.valor == Decimal("100.00")

    def test_valor_liquido_desconta_desconto(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.valor_liquido is not None
        assert doc.valor_liquido.valor == Decimal("95.00")

    def test_cnpj_emitente_extraido(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.cnpj_emitente is not None
        assert doc.cnpj_emitente.numero == "12345678000195"

    def test_nome_emitente(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.nome_emitente == "EMPRESA TESTE LTDA"

    def test_chave_acesso(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.chave_acesso == "35240312345678000195550010000000011000000011"

    def test_cfop_predominante_no_documento(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.cfop == "5102"

    def test_confidence_scores_presentes(self, nfe_saida: Path) -> None:
        from core.domain.entities import ConfidenceScore
        doc = parsear_nfe(nfe_saida)
        assert len(doc.confidence_scores) > 0
        assert all(isinstance(s, ConfidenceScore) for s in doc.confidence_scores)

    def test_sem_revisao_quando_completo(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.precisa_revisao is False
        assert doc.motivo_revisao is None


# =============================================================
# TESTES — NATUREZA POR CFOP
# =============================================================

class TestNaturezaPorCFOP:
    def test_cfop_saida_e_credito(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.natureza_operacao == NaturezaLancamento.CREDITO

    def test_cfop_entrada_e_debito(self, nfe_entrada: Path) -> None:
        doc = parsear_nfe(nfe_entrada)
        assert doc.natureza_operacao == NaturezaLancamento.DEBITO


# =============================================================
# TESTES — METADADOS NFe
# =============================================================

class TestMetadadosNFe:
    def test_metadados_presentes(self, nfe_saida: Path) -> None:
        doc = parsear_nfe(nfe_saida)
        assert doc.metadados_nfe is not None
        assert isinstance(doc.metadados_nfe, MetadadosNFe)

    def test_cfop_itens(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert "5102" in meta.cfop_itens

    def test_ncm_itens(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert "84713012" in meta.ncm_itens

    def test_cst_extraido(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert meta.cst_icms == "00"

    def test_cnpj_destinatario(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert meta.cnpj_destinatario is not None
        assert meta.cnpj_destinatario.numero == "98765432000198"

    def test_valores_tributarios_sao_dinheiro(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert isinstance(meta.valor_icms, Dinheiro)
        assert isinstance(meta.valor_pis, Dinheiro)
        assert isinstance(meta.valor_cofins, Dinheiro)
        assert isinstance(meta.valor_ipi, Dinheiro)

    def test_valor_icms(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert meta.valor_icms.valor == Decimal("18.00")

    def test_total_tributos(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        esperado = Decimal("18.00") + Decimal("1.65") + Decimal("7.60") + Decimal("0.00")
        assert meta.total_tributos.valor == esperado

    def test_finalidade_normal(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert meta.finalidade == 1
        assert meta.e_devolucao is False
        assert meta.e_complementar is False

    def test_finalidade_devolucao(self, nfe_devolucao: Path) -> None:
        meta = parsear_nfe(nfe_devolucao).metadados_nfe
        assert meta.finalidade == 4
        assert meta.e_devolucao is True

    def test_natureza_operacao_texto(self, nfe_saida: Path) -> None:
        meta = parsear_nfe(nfe_saida).metadados_nfe
        assert "Venda" in meta.natureza_operacao_texto


# =============================================================
# TESTES — MULTIPLOS ITENS
# =============================================================

class TestMultiplosItens:
    def test_cfop_predominante(self, nfe_multiplos_itens: Path) -> None:
        meta = parsear_nfe(nfe_multiplos_itens).metadados_nfe
        # 5102 aparece 2x, 5101 aparece 1x
        assert meta.cfop_predominante == "5102"

    def test_todos_cfop_capturados(self, nfe_multiplos_itens: Path) -> None:
        meta = parsear_nfe(nfe_multiplos_itens).metadados_nfe
        assert len(meta.cfop_itens) == 3

    def test_todos_ncm_capturados(self, nfe_multiplos_itens: Path) -> None:
        meta = parsear_nfe(nfe_multiplos_itens).metadados_nfe
        assert len(meta.ncm_itens) == 3

    def test_cfop_itens_e_tuple(self, nfe_multiplos_itens: Path) -> None:
        meta = parsear_nfe(nfe_multiplos_itens).metadados_nfe
        assert isinstance(meta.cfop_itens, tuple)
        assert isinstance(meta.ncm_itens, tuple)


# =============================================================
# TESTES — REVISÃO AUTOMÁTICA
# =============================================================

class TestRevisaoAutomatica:
    def test_marca_revisao_sem_chave(self, nfe_sem_chave: Path) -> None:
        doc = parsear_nfe(nfe_sem_chave)
        assert doc.precisa_revisao is True
        assert doc.motivo_revisao is not None
        assert "chave" in doc.motivo_revisao

    def test_marca_revisao_valor_zero(self, nfe_sem_chave: Path) -> None:
        doc = parsear_nfe(nfe_sem_chave)
        assert "valor" in doc.motivo_revisao


# =============================================================
# TESTES — ERROS
# =============================================================

class TestErros:
    def test_arquivo_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parsear_nfe(tmp_path / "nao_existe.xml")

    def test_xml_malformado(self, tmp_path: Path) -> None:
        f = tmp_path / "ruim.xml"
        f.write_text("<broken><xml>", encoding="utf-8")
        with pytest.raises(NFeInvalidaError, match="malformado"):
            parsear_nfe(f)

    def test_xml_sem_nfe(self, tmp_path: Path) -> None:
        f = tmp_path / "outro.xml"
        f.write_text('<?xml version="1.0"?><root><dados>123</dados></root>', encoding="utf-8")
        with pytest.raises(NFeInvalidaError):
            parsear_nfe(f)


# =============================================================
# TESTES — MetadadosNFe VALUE OBJECT
# =============================================================

class TestMetadadosNFeValueObject:
    def _meta(self, **kwargs):
        defaults = dict(
            chave_acesso="35240312345678000195550010000000011000000011",
            finalidade=1,
            natureza_operacao_texto="Venda",
            cfop_itens=("5102",),
            ncm_itens=("84713012",),
            cst_icms="00",
            cnpj_destinatario=None,
            valor_icms=Dinheiro(Decimal("0")),
            valor_pis=Dinheiro(Decimal("0")),
            valor_cofins=Dinheiro(Decimal("0")),
            valor_ipi=Dinheiro(Decimal("0")),
        )
        defaults.update(kwargs)
        return MetadadosNFe(**defaults)

    def test_imutavel(self) -> None:
        meta = self._meta()
        with pytest.raises((AttributeError, TypeError)):
            meta.finalidade = 2  # type: ignore

    def test_cfop_predominante_vazio(self) -> None:
        meta = self._meta(cfop_itens=())
        assert meta.cfop_predominante is None

    def test_total_tributos_zero(self) -> None:
        meta = self._meta()
        assert meta.total_tributos.valor == Decimal("0")
