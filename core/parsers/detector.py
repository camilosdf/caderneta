"""Detector de origem de documento.

Determina o tipo do documento e roteia para o pipeline correto.
Prioridade: XML NF-e > OFX/CSV > PDF com texto > PDF imagem > Imagem
"""

import hashlib
from pathlib import Path

from core.domain.entities import TipoDocumento


class DocumentoDuplicadoError(Exception):
    pass


class TipoNaoSuportadoError(Exception):
    pass


class DetectorDocumento:
    EXTENSOES_XML = {".xml"}
    EXTENSOES_OFX = {".ofx", ".qfx"}
    EXTENSOES_CSV = {".csv", ".txt"}
    EXTENSOES_PDF = {".pdf"}
    EXTENSOES_IMG = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}

    def detectar(self, filepath: Path) -> TipoDocumento:
        """Detecta o tipo do documento pelo conteúdo, não pela extensão."""
        if not filepath.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        sufixo = filepath.suffix.lower()

        if sufixo in self.EXTENSOES_XML:
            if self._e_nfe(filepath):
                return TipoDocumento.NFE_XML
            raise TipoNaoSuportadoError(
                f"XML não identificado como NF-e: {filepath.name}"
            )

        if sufixo in self.EXTENSOES_OFX:
            return TipoDocumento.OFX

        if sufixo in self.EXTENSOES_CSV:
            return TipoDocumento.CSV

        if sufixo in self.EXTENSOES_PDF:
            if self._pdf_tem_texto(filepath):
                return TipoDocumento.PDF_TEXTO
            return TipoDocumento.PDF_IMAGEM

        if sufixo in self.EXTENSOES_IMG:
            return TipoDocumento.IMAGEM

        raise TipoNaoSuportadoError(
            f"Extensão não suportada: {sufixo}. "
            f"Suportados: XML, OFX, CSV, PDF, JPG, PNG, TIFF"
        )

    def calcular_hash(self, filepath: Path) -> str:
        """Calcula SHA-256 do arquivo para deduplicação."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _e_nfe(self, filepath: Path) -> bool:
        try:
            conteudo = filepath.read_bytes()[:2048].decode("utf-8", errors="ignore")
            return "nfeProc" in conteudo or "<NFe " in conteudo or "<NFe>" in conteudo
        except Exception:
            return False

    def _pdf_tem_texto(self, filepath: Path) -> bool:
        try:
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages[:3]:
                    texto = page.extract_text()
                    if texto and len(texto.strip()) > 50:
                        return True
            return False
        except Exception:
            return False
