"""Parser CSV — Bradesco.

Formato: Data;Histórico;Docto;Crédito (R$);Débito (R$);Saldo (R$) (latin-1)
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from core.domain.entities import Documento
from core.parsers.csv.base import criar_documento, parse_data_br


def parsear_bradesco(filepath: Path) -> Iterator[Documento]:
    with open(filepath, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = parse_data_br(linha.get("Data", ""))
                descricao = linha.get("Histórico", linha.get("Historico", "")).strip()

                credito_str = linha.get("Crédito (R$)", "0").replace(".", "").replace(",", ".")
                debito_str  = linha.get("Débito (R$)",  "0").replace(".", "").replace(",", ".")

                credito = Decimal(credito_str or "0")
                debito  = Decimal(debito_str  or "0")

                if credito > 0:
                    valor = credito
                elif debito > 0:
                    valor = -debito
                else:
                    continue

                yield criar_documento(filepath, data, valor, descricao, "bradesco")
            except (ValueError, InvalidOperation, KeyError):
                continue
