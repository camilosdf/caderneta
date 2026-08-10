"""Testes do caso de uso ProcessarFaturaCartao — ADR 010, Fase 2.

Herméticos: nem pdfplumber real nem OCR real são exercitados de fato —
pdfplumber.open é mockado (mesmo padrão hermético já usado em
test_ocr_plugin.py para SpikeOCR/PaddleOCR) e o OCR é substituído por
um fake que implementa ExtratorDeArquivoPort por duck typing.

Textos usados são SINTÉTICOS — mesmo aviso de evidência do parser
testado em test_fatura_cartao_parser.py.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from core.application.use_cases.processar_fatura_cartao import (
    DocumentoNaoEhFaturaError,
    OCRNaoDisponivelError,
    ProcessarFaturaCartaoUseCase,
)
from core.domain.entities import StatusFechamentoFatura, TipoDocumento
from core.parsers.detector import TipoNaoSuportadoError

_TEXTO_FATURA_SINTETICA_FECHADA = """\
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
06/08 IFOOD DELIVERY R$ 48,50
Total desta fatura R$ 74,40
"""

_TEXTO_FATURA_SINTETICA_DIVERGENTE = """\
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
Total desta fatura R$ 999,00
"""

_TEXTO_SEM_CAMPOS_DE_FATURA = "Este texto não contém nenhum campo de fatura reconhecível."


def _detector_mock(tipo: TipoDocumento, hash_doc: str = "hash-fake") -> MagicMock:
    mock = MagicMock()
    mock.detectar.return_value = tipo
    mock.calcular_hash.return_value = hash_doc
    return mock


def _pdfplumber_mock(texto: str):
    """Context manager mockado para pdfplumber.open — 1 página com o texto dado."""
    pagina = MagicMock()
    pagina.extract_text.return_value = texto
    pdf_mock = MagicMock()
    pdf_mock.__enter__.return_value.pages = [pagina]
    pdf_mock.__exit__.return_value = False
    return pdf_mock


class _FakeOCRPort:
    """Fake que satisfaz ExtratorDeArquivoPort por duck typing, sem PaddleOCR."""

    def __init__(self, texto: str = "", erro: str | None = None):
        self._texto = texto
        self._erro = erro

    def extrair_de_arquivo(self, filepath: Path) -> dict[str, tuple[str, float]]:
        if self._erro:
            return {"erro_ocr": (self._erro, 0.0)}
        return {"texto_bruto": (self._texto, 0.7)}


# =============================================================
# CAMINHO FELIZ — PDF_TEXTO
# =============================================================

class TestPdfTexto:
    def test_fatura_fechada_gera_agregado_completo(self):
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_SINTETICA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert resultado.documento.tipo == TipoDocumento.PDF_TEXTO
        assert resultado.fatura.data_vencimento == date(2026, 9, 15)
        assert resultado.fatura.valor_total_declarado.valor == Decimal("74.40")
        assert len(resultado.fatura.itens) == 2
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_documento_criado_com_hash_do_detector(self):
        detector = _detector_mock(TipoDocumento.PDF_TEXTO, hash_doc="hash-especifico")
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_SINTETICA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert resultado.documento.hash_sha256 == "hash-especifico"

    def test_cartao_id_propagado_para_fatura(self):
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)
        cartao_id = uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_SINTETICA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4(), cartao_id=cartao_id)

        assert resultado.fatura.cartao_id == cartao_id


# =============================================================
# CAMINHO FELIZ — PDF_IMAGEM (OCR)
# =============================================================

class TestPdfImagem:
    def test_fatura_via_ocr_gera_agregado(self):
        detector = _detector_mock(TipoDocumento.PDF_IMAGEM)
        ocr = _FakeOCRPort(texto=_TEXTO_FATURA_SINTETICA_FECHADA)
        uc = ProcessarFaturaCartaoUseCase(detector=detector, ocr_plugin=ocr)

        resultado = uc.executar(Path("fatura_scan.pdf"), empresa_id=uuid4())

        assert resultado.documento.tipo == TipoDocumento.PDF_IMAGEM
        assert len(resultado.fatura.itens) == 2
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.FECHADA


# =============================================================
# TESTES NEGATIVOS — documento incompatível / extração ambígua
# =============================================================

class TestNegativos:
    def test_tipo_nao_pdf_levanta_erro(self):
        """Documento incompatível: CSV não é aceito por este use case."""
        detector = _detector_mock(TipoDocumento.CSV)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with pytest.raises(TipoNaoSuportadoError):
            uc.executar(Path("extrato.csv"), empresa_id=uuid4())

    def test_pdf_sem_campos_de_fatura_levanta_erro(self):
        """Extração ambígua: nenhum campo de cabeçalho reconhecido."""
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with (
            patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_SEM_CAMPOS_DE_FATURA)),
            pytest.raises(DocumentoNaoEhFaturaError),
        ):
            uc.executar(Path("nao_e_fatura.pdf"), empresa_id=uuid4())

    def test_pdf_imagem_sem_ocr_injetado_levanta_erro(self):
        """PDF_IMAGEM sem ExtratorDeArquivoPort injetado — nunca criado
        internamente (core/ não importa ai/)."""
        detector = _detector_mock(TipoDocumento.PDF_IMAGEM)
        uc = ProcessarFaturaCartaoUseCase(detector=detector, ocr_plugin=None)

        with pytest.raises(OCRNaoDisponivelError):
            uc.executar(Path("fatura_scan.pdf"), empresa_id=uuid4())

    def test_erro_de_ocr_levanta_erro(self):
        detector = _detector_mock(TipoDocumento.PDF_IMAGEM)
        ocr = _FakeOCRPort(erro="Arquivo corrompido")
        uc = ProcessarFaturaCartaoUseCase(detector=detector, ocr_plugin=ocr)

        with pytest.raises(DocumentoNaoEhFaturaError):
            uc.executar(Path("fatura_corrompida.pdf"), empresa_id=uuid4())


# =============================================================
# DIVERGÊNCIA E BAIXA CONFIANÇA — D5, revisão humana
# =============================================================

class TestDivergenciaERevisao:
    def test_fatura_divergente_nao_levanta_excecao(self):
        """D5 — divergência não bloqueia, marca para revisão."""
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_SINTETICA_DIVERGENTE)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.DIVERGENTE
        assert any("divergente" in aviso.lower() for aviso in resultado.avisos)

    def test_itens_baixa_confianca_sao_listados_para_revisao(self):
        """Todo item desta primeira versão fica abaixo do limiar de
        confiável (ver AVISO DE EVIDÊNCIA do parser) — todos devem
        aparecer em itens_baixa_confianca."""
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_SINTETICA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert len(resultado.itens_baixa_confianca) == len(resultado.fatura.itens)
        assert any("revisão manual" in aviso.lower() for aviso in resultado.avisos)

    def test_fatura_sem_itens_gera_aviso_sem_levantar_excecao(self):
        texto = "Vencimento: 15/09/2026\nTotal desta fatura R$ 0,00\n"
        detector = _detector_mock(TipoDocumento.PDF_TEXTO)
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(texto)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert resultado.fatura.itens == []
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.PENDENTE
        assert any("nenhum item" in aviso.lower() for aviso in resultado.avisos)
