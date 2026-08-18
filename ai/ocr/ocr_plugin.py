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

        Diferente de extrair_campos() (que recebe só uma string, sem
        contexto de confiança por linha), este método tem acesso ao
        ResultadoOCR completo e propaga a confiança REAL do PaddleOCR
        por linha (ResultadoOCR.linhas[].confiança), em vez de uma
        constante fixa. Quando uma linha não tem confiança própria
        disponível (ex.: texto sintético em teste, sem OCR real por
        trás), usa confiança_media do documento como fallback — nunca
        um valor inventado.
        """
        resultado = self._spike.processar_documento(filepath)

        if resultado.erro:
            return {"erro_ocr": (resultado.erro, 0.0)}

        campos = _extrair_campos_com_confianca_real(resultado)

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


def _extrair_campos_com_confianca_real(resultado) -> dict[str, tuple[str, float]]:
    """Mesma heurística de extrair_campos(), mas usa a confiança REAL
    do PaddleOCR por linha (ResultadoOCR.linhas) em vez de uma
    constante fixa — correção autorizada para deixar de descartar a
    confiança real produzida pelo OCR.

    Regra: ResultadoOCR.linhas -> confiança por linha, quando
    disponível; caso contrário (linha sem correspondência exata,
    ou 'linhas' vazio — ex.: texto sintético em teste), usa
    confiança_media do documento como fallback. Nunca inventa um
    valor de confiança.
    """
    texto = resultado.texto_extraído
    if not texto.strip():
        return {}

    linhas_texto = [linha for linha in texto.strip().split("\n") if linha.strip()]
    confianca_por_texto = {
        item["texto"]: item["confiança"] for item in resultado.linhas
    }
    confianca_fallback = resultado.confiança_media

    campos: dict[str, tuple[str, float]] = {
        "texto_bruto": (texto.strip(), confianca_fallback),
        "n_linhas": (str(len(linhas_texto)), 1.0),
    }

    for linha in linhas_texto:
        confianca_linha = confianca_por_texto.get(linha, confianca_fallback)
        linha_upper = linha.upper()

        if "CNPJ" in linha_upper or _parece_cnpj(linha):
            candidato = _extrair_cnpj(linha)
            if candidato:
                campos["cnpj_emitente"] = (candidato, confianca_linha)

        if any(kw in linha_upper for kw in ("TOTAL", "VALOR TOTAL", "VALOR A PAGAR")):
            candidato = _extrair_valor(linha)
            if candidato:
                campos.setdefault("valor_total", (candidato, confianca_linha))

    return campos
