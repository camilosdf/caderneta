"""Alias de compatibilidade — módulo migrado para core.parsers.detector.

Este arquivo será removido na v0.006.000.
Importe diretamente de core.parsers.detector para novos desenvolvimentos.
"""

from core.parsers.detector import (  # noqa: F401
    DetectorDocumento,
    DocumentoDuplicadoError,
    TipoNaoSuportadoError,
)
