"""Parser CSV — Banco Inter.

Formato: Data;Tipo;Descrição;Valor (UTF-8-sig, ponto-e-vírgula)
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from core.domain.entities import Documento
from core.parsers.csv.base import criar_documento, parse_data_br


def parsear_inter(filepath: Path) -> Iterator[Documento]:
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = parse_data_br(linha.get("Data", ""))
                valor_str = linha.get("Valor", "0").replace(".", "").replace(",", ".")
                valor = Decimal(valor_str)
                descricao = linha.get("Descrição", linha.get("Descricao", "")).strip()

                yield criar_documento(filepath, data, valor, descricao, "inter")
            except (ValueError, InvalidOperation, KeyError):
                continue
