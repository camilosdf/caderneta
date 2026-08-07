"""Alias de compatibilidade — módulo migrado para core.parsers.csv.

Este arquivo será removido na v0.006.000.
Importe diretamente de core.parsers.csv para novos desenvolvimentos.
"""

from core.parsers.csv import (  # noqa: F401
    BancoNaoIdentificadoError,
    detectar_banco,
    parsear_bradesco as _parsear_bradesco,
    parsear_csv,
    parsear_inter as _parsear_inter,
    parsear_itau as _parsear_itau,
    parsear_nubank as _parsear_nubank,
    parsear_santander as _parsear_santander,
)
from core.parsers.csv.base import criar_documento as _criar_documento  # noqa: F401
from core.parsers.csv.base import parse_data_br as _parse_data_br  # noqa: F401

# Nomes privados mantidos para testes existentes que importam diretamente
_parsear_nubank = _parsear_nubank
_parsear_inter = _parsear_inter
_parsear_itau = _parsear_itau
_parsear_bradesco = _parsear_bradesco
_parsear_santander = _parsear_santander
_criar_documento = _criar_documento
_parse_data_br = _parse_data_br
