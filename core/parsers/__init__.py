"""API pública unificada dos parsers do Caderneta.

Uso:
    from core.parsers import DetectorDocumento, parsear_csv, parsear_nfe, OFXParser
"""

from core.parsers.csv import (  # noqa: F401
    BancoNaoIdentificadoError,
    detectar_banco,
    parsear_bradesco,
    parsear_csv,
    parsear_inter,
    parsear_itau,
    parsear_nubank,
    parsear_santander,
)
from core.parsers.detector import (  # noqa: F401
    DetectorDocumento,
    DocumentoDuplicadoError,
    TipoNaoSuportadoError,
)
from core.parsers.nfe import parsear_nfe  # noqa: F401
from core.parsers.ofx import OFXParser  # noqa: F401

__all__ = [
    # Detector
    "DetectorDocumento",
    "DocumentoDuplicadoError",
    "TipoNaoSuportadoError",
    # NF-e
    "parsear_nfe",
    # OFX
    "OFXParser",
    # CSV
    "parsear_csv",
    "detectar_banco",
    "parsear_nubank",
    "parsear_inter",
    "parsear_itau",
    "parsear_bradesco",
    "parsear_santander",
    "BancoNaoIdentificadoError",
]

# Adaptadores e Protocol
from core.parsers.adapters import CSVParser, NFeParser, ParserProtocol  # noqa: F401
