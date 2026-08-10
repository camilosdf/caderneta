"""Testes do OCRPlugin (Etapa 7.4).

Herméticos: PaddleOCR nunca é importado. O SpikeOCR é mockado
para isolar o OCRPlugin da dependência de GPU/modelo.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai.ocr.ocr_plugin import OCRPlugin, _extrair_cnpj, _extrair_valor, _parece_cnpj
from ai.ocr.spike import ResultadoOCR
from core.ports.classification import ExtractionPort


def _spike_mock(
    texto: str = "",
    confianca: float = 0.95,
    erro: str | None = None,
) -> MagicMock:
    """Mock do SpikeOCR que retorna um ResultadoOCR configurável."""
    mock = MagicMock()
    mock.processar_documento.return_value = ResultadoOCR(
        arquivo="teste.pdf",
        texto_extraído=texto,
        tempo_ms=123.4,
        confiança_media=confianca,
        linhas=[],
        erro=erro,
    )
    return mock


# =============================================================
# CONTRATO
# =============================================================

class TestOCRPluginContrato:
    def test_satisfaz_extraction_port(self) -> None:
        """ExtractionPort é satisfeito por duck typing — sem herança."""
        plugin = OCRPlugin(spike=_spike_mock())
        assert isinstance(plugin, ExtractionPort)

    def test_extrair_campos_retorna_dict(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos("qualquer texto", "pdf_imagem")
        assert isinstance(campos, dict)

    def test_cada_campo_e_tuple_str_float(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos("texto simples", "pdf_imagem")
        for valor, conf in campos.values():
            assert isinstance(valor, str)
            assert isinstance(conf, float)
            assert 0.0 <= conf <= 1.0


# =============================================================
# EXTRAIR_CAMPOS
# =============================================================

class TestExtrairCampos:
    def test_texto_vazio_retorna_dict_vazio(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        assert plugin.extrair_campos("", "pdf_imagem") == {}
        assert plugin.extrair_campos("   ", "pdf_imagem") == {}

    def test_texto_bruto_sempre_presente(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos("texto qualquer", "pdf_imagem")
        assert "texto_bruto" in campos
        assert campos["texto_bruto"][0] == "texto qualquer"

    def test_n_linhas_correto(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        texto = "linha 1\nlinha 2\nlinha 3"
        campos = plugin.extrair_campos(texto, "pdf_imagem")
        assert campos["n_linhas"] == ("3", 1.0)

    def test_extrai_cnpj(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos(
            "CNPJ: 12.345.678/0001-90\nNome: Empresa Teste",
            "pdf_imagem",
        )
        assert "cnpj_emitente" in campos
        assert "12.345.678/0001-90" in campos["cnpj_emitente"][0]

    def test_extrai_valor_total(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos(
            "Produto: Caneta\nVALOR TOTAL R$ 1.500,00",
            "pdf_imagem",
        )
        assert "valor_total" in campos

    def test_sem_cnpj_campo_nao_presente(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_campos("Texto sem CNPJ algum", "pdf_imagem")
        assert "cnpj_emitente" not in campos

    def test_tipo_documento_aceito_sem_erro(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        for tipo in ("pdf_imagem", "imagem", "outro"):
            campos = plugin.extrair_campos("texto", tipo)
            assert "texto_bruto" in campos


# =============================================================
# EXTRAIR_DE_ARQUIVO
# =============================================================

class TestExtrairDeArquivo:
    def test_delega_ao_spike(self) -> None:
        spike = _spike_mock(texto="CNPJ 12.345.678/0001-90\nVALOR TOTAL R$ 100,00")
        plugin = OCRPlugin(spike=spike)
        campos = plugin.extrair_de_arquivo(Path("documento.pdf"))

        spike.processar_documento.assert_called_once_with(Path("documento.pdf"))
        assert "texto_bruto" in campos

    def test_inclui_confianca_ocr(self) -> None:
        spike = _spike_mock(texto="texto", confianca=0.92)
        plugin = OCRPlugin(spike=spike)
        campos = plugin.extrair_de_arquivo(Path("doc.pdf"))

        assert "confianca_ocr" in campos
        assert float(campos["confianca_ocr"][0]) == pytest.approx(0.92)

    def test_inclui_tempo_ms(self) -> None:
        plugin = OCRPlugin(spike=_spike_mock())
        campos = plugin.extrair_de_arquivo(Path("doc.pdf"))
        assert "tempo_ms" in campos

    def test_erro_ocr_retorna_campo_erro(self) -> None:
        spike = _spike_mock(erro="Arquivo corrompido")
        plugin = OCRPlugin(spike=spike)
        campos = plugin.extrair_de_arquivo(Path("corrompido.pdf"))

        assert "erro_ocr" in campos
        assert campos["erro_ocr"][1] == 0.0  # confidence zero quando há erro

    def test_spike_nao_inicializado_se_nao_usado(self) -> None:
        """OCRPlugin não dispara PaddleOCR até processar_documento ser chamado."""
        plugin = OCRPlugin()  # sem mock — spike real criado mas não inicializado
        assert plugin._spike._ocr is None  # lazy — não carregado ainda

    def test_extrair_de_arquivo_usa_confianca_real_por_linha(self) -> None:
        """Correção autorizada: confiança real do PaddleOCR por linha,
        não mais uma constante fixa (0.85)."""
        linha_cnpj = "CNPJ: 12.345.678/0001-90"
        mock = MagicMock()
        mock.processar_documento.return_value = ResultadoOCR(
            arquivo="teste.pdf",
            texto_extraído=linha_cnpj,
            tempo_ms=1.0,
            confiança_media=0.60,
            linhas=[{"texto": linha_cnpj, "confiança": 0.42, "bbox": []}],
        )
        plugin = OCRPlugin(spike=mock)
        campos = plugin.extrair_de_arquivo(Path("teste.pdf"))

        assert campos["cnpj_emitente"][1] == pytest.approx(0.42)
        assert campos["cnpj_emitente"][1] != 0.85

    def test_extrair_de_arquivo_usa_fallback_quando_linha_sem_confianca_propria(self) -> None:
        """Sem correspondência em ResultadoOCR.linhas (ex.: texto sintético),
        usa confiança_media como fallback — nunca inventa um valor."""
        spike = _spike_mock(texto="VALOR TOTAL R$ 50,00", confianca=0.77)
        plugin = OCRPlugin(spike=spike)
        campos = plugin.extrair_de_arquivo(Path("teste.pdf"))

        assert campos["valor_total"][1] == pytest.approx(0.77)


# =============================================================
# UTILITÁRIOS
# =============================================================

class TestUtilitarios:
    def test_parece_cnpj_com_formato_padrao(self) -> None:
        assert _parece_cnpj("12.345.678/0001-90") is True

    def test_parece_cnpj_sem_pontuacao(self) -> None:
        assert _parece_cnpj("12345678000190") is True

    def test_parece_cnpj_texto_livre(self) -> None:
        assert _parece_cnpj("CNPJ: 12.345.678/0001-90") is True

    def test_parece_cnpj_false_para_texto_sem_cnpj(self) -> None:
        assert _parece_cnpj("Texto completamente normal") is False

    def test_extrair_cnpj_retorna_match(self) -> None:
        resultado = _extrair_cnpj("CNPJ 12.345.678/0001-90 validade")
        assert resultado is not None
        assert "12.345.678/0001-90" in resultado

    def test_extrair_cnpj_none_sem_cnpj(self) -> None:
        assert _extrair_cnpj("Nenhum CNPJ aqui") is None

    def test_extrair_valor_com_rs(self) -> None:
        resultado = _extrair_valor("TOTAL R$ 1.500,00")
        assert resultado is not None

    def test_extrair_valor_sem_rs(self) -> None:
        resultado = _extrair_valor("Sem valor monetário")
        # Pode não encontrar ou encontrar número qualquer — não deve lançar exceção
        assert resultado is None or isinstance(resultado, str)
