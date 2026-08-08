"""OCRPlugin — adapter entre SpikeOCR e ExtractionPort (Etapa 7.4).

Transforma a SpikeOCR (prova de conceito técnica) em um componente
do pipeline real, satisfazendo ExtractionPort via duck typing.

Responsabilidade: extração de texto bruto de documentos não estruturados
(PDFs, imagens). NÃO interpreta, NÃO classifica, NÃO decide — apenas
extrai o texto para que o pipeline determinístico tente processar.

Limitação explícita: extração de campos semânticos (CNPJ, valor total,
data de emissão de uma NF-e) exigiria um modelo NER ou prompt de LLM —
isso é escopo da Etapa 7.5 (LLMPort), não deste adapter.
"""

import re
from pathlib import Path

from ai.ocr.spike import SpikeOCR


class OCRPlugin:
    """Implementa ExtractionPort via duck typing usando SpikeOCR.

    Usado pelo pipeline quando o tipo de documento é PDF_IMAGEM ou IMAGEM
    — casos em que o parser determinístico não consegue extrair texto
    diretamente do arquivo.
    """

    def __init__(self, spike: SpikeOCR | None = None) -> None:
        """
        Args:
            spike: instância de SpikeOCR. None → cria uma nova.
                   Injetar em testes para evitar importar PaddleOCR.
        """
        self._spike = spike or SpikeOCR()

    # ── ExtractionPort ────────────────────────────────────────────────────

    def extrair_campos(
        self,
        texto: str,
        tipo_documento: str,
    ) -> dict[str, tuple[str, float]]:
        """Extrai campos do texto bruto retornado pelo OCR.

        Args:
            texto: texto bruto já extraído (via extrair_de_arquivo).
            tipo_documento: "pdf_imagem" | "imagem" — reservado para
                            versões futuras com modelos específicos.

        Returns:
            dict com campos extraídos: {campo: (valor_str, confidence)}
        """
        if not texto.strip():
            return {}

        linhas = [linha for linha in texto.strip().split("\n") if linha.strip()]
        confianca_estimada = 0.85

        campos: dict[str, tuple[str, float]] = {
            "texto_bruto": (texto.strip(), confianca_estimada),
            "n_linhas": (str(len(linhas)), 1.0),
        }

        for linha in linhas:
            linha_upper = linha.upper()

            if "CNPJ" in linha_upper or _parece_cnpj(linha):
                candidato = _extrair_cnpj(linha)
                if candidato:
                    campos["cnpj_emitente"] = (candidato, confianca_estimada)

            if any(kw in linha_upper for kw in ("TOTAL", "VALOR TOTAL", "VALOR A PAGAR")):
                candidato = _extrair_valor(linha)
                if candidato:
                    campos.setdefault("valor_total", (candidato, confianca_estimada))

        return campos

    def extrair_de_arquivo(self, filepath: Path) -> dict[str, tuple[str, float]]:
        """Extrai campos diretamente de um arquivo (PDF/imagem).

        Ponto de entrada preferencial quando há acesso ao arquivo —
        usa PaddleOCR via SpikeOCR, que carrega o modelo lazy.
        """
        resultado = self._spike.processar_documento(filepath)

        if resultado.erro:
            return {"erro_ocr": (resultado.erro, 0.0)}

        campos = self.extrair_campos(resultado.texto_extraído, "pdf_imagem")

        campos["confianca_ocr"] = (
            str(round(resultado.confiança_media, 4)),
            resultado.confiança_media,
        )
        campos["tempo_ms"] = (str(resultado.tempo_ms), 1.0)

        return campos


# =============================================================
# UTILITÁRIOS DE EXTRAÇÃO HEURÍSTICA
# =============================================================

def _parece_cnpj(texto: str) -> bool:
    """True se o texto contém um padrão que lembra um CNPJ."""
    return bool(re.search(r"\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\-]?\d{4}[.\-]?\d{2}", texto))


def _extrair_cnpj(texto: str) -> str | None:
    """Extrai o primeiro CNPJ encontrado na linha, formatado."""
    m = re.search(r"\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\-]?\d{4}[.\-]?\d{2}", texto)
    return m.group(0).strip() if m else None


def _extrair_valor(texto: str) -> str | None:
    """Extrai o primeiro valor monetário (R$) encontrado na linha."""
    m = re.search(r"R?\$?\s*[\d.,]+", texto)
    return m.group(0).strip() if m else None
