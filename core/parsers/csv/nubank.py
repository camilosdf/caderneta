"""Parser CSV — Nubank (Cartão de Crédito).

Formato: date,title,amount (inglês, vírgula, UTF-8-sig)
Semântica: valor positivo = débito (saída do cliente na fatura).
"""

import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from typing import Iterator

from core.domain.entities import Documento
from core.parsers.csv.base import criar_documento


def parsear_nubank(filepath: Path) -> Iterator[Documento]:
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")
        for linha in reader:
            try:
                data_str = linha.get("date", "")
                data = datetime.strptime(data_str, "%Y-%m-%d").date()
                descricao = linha.get("title", "").strip()
                valor_str = linha.get("amount", "0").replace(",", ".")
                valor = Decimal(valor_str)

                if not descricao:
                    continue

                # Nubank fatura: positivo = saída (débito) — inverte sinal
                yield criar_documento(filepath, data, -valor, descricao, "nubank")
            except (ValueError, InvalidOperation, KeyError):
                continue
