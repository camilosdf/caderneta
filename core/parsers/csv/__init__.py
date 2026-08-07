"""Parsers CSV bancários — API pública.

Uso:
    from core.parsers.csv import parsear_csv, detectar_banco
"""

from pathlib import Path
from typing import Iterator

from core.domain.entities import Documento
from core.parsers.csv.base import BancoNaoIdentificadoError, criar_documento, parse_data_br
from core.parsers.csv.bradesco import parsear_bradesco
from core.parsers.csv.inter import parsear_inter
from core.parsers.csv.itau import parsear_itau
from core.parsers.csv.nubank import parsear_nubank
from core.parsers.csv.santander import parsear_santander

__all__ = [
    "parsear_csv",
    "detectar_banco",
    "parsear_nubank",
    "parsear_inter",
    "parsear_itau",
    "parsear_bradesco",
    "parsear_santander",
    "BancoNaoIdentificadoError",
]

_PARSERS = {
    "inter":     parsear_inter,
    "itau":      parsear_itau,
    "nubank":    parsear_nubank,
    "bradesco":  parsear_bradesco,
    "santander": parsear_santander,
}


def detectar_banco(filepath: Path) -> str:
    """Detecta o banco pelo cabeçalho do CSV."""
    with open(filepath, encoding="utf-8-sig", errors="ignore") as f:
        primeiras_linhas = [f.readline() for _ in range(5)]

    conteudo = "\n".join(primeiras_linhas).upper()

    if "INTER" in conteudo or "BANCO INTER" in conteudo:
        return "inter"
    if "ITAÚ" in conteudo or "ITAU" in conteudo:
        return "itau"
    if "BRADESCO" in conteudo:
        return "bradesco"
    if "NUBANK" in conteudo or "NU PAGAMENTOS" in conteudo:
        return "nubank"
    if "SANTANDER" in conteudo:
        return "santander"

    raise BancoNaoIdentificadoError(
        f"Banco não identificado no arquivo {filepath.name}. "
        f"Verifique se é um extrato CSV válido."
    )


def parsear_csv(filepath: Path) -> Iterator[Documento]:
    """Detecta o banco e delega ao parser correto."""
    banco = detectar_banco(filepath)
    parser = _PARSERS.get(banco)
    if not parser:
        raise BancoNaoIdentificadoError(f"Parser não implementado para: {banco}")
    yield from parser(filepath)
