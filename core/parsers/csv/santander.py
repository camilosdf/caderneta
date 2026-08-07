"""Parser CSV — Santander.

Formato: Data;Histórico;Valor (latin-1, ponto-e-vírgula)
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from core.domain.entities import Documento
from core.parsers.csv.base import criar_documento, parse_data_br


def parsear_santander(filepath: Path) -> Iterator[Documento]:
    with open(filepath, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = parse_data_br(linha.get("Data", ""))
                descricao = linha.get("Histórico", linha.get("Historico", "")).strip()
                valor_str = linha.get("Valor", "0").replace(".", "").replace(",", ".")
                valor = Decimal(valor_str)

                yield criar_documento(filepath, data, valor, descricao, "santander")
            except (ValueError, InvalidOperation, KeyError):
                continue
