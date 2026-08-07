"""Alias de compatibilidade — módulo migrado para core.parsers.ofx.

Este arquivo será removido na v0.006.000.
Importe diretamente de core.parsers.ofx para novos desenvolvimentos.
"""

from core.parsers.ofx import OFXParser  # noqa: F401

# Alias público mantido
DocumentoFinanceiro = None  # era Documento — use core.domain.entities.Documento
