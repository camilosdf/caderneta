"""Helpers compartilhados pelos parsers CSV bancários."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from core.domain.entities import (
    ConfidenceScore,
    Dinheiro,
    Documento,
    FonteExtracao,
    NaturezaLancamento,
    TipoDocumento,
)

# Alias público para retrocompatibilidade
DocumentoFinanceiro = Documento


class BancoNaoIdentificadoError(Exception):
    pass


def criar_documento(
    filepath: Path,
    data: date,
    valor: Decimal,
    descricao: str,
    banco: str,
) -> Documento:
    """Cria um Documento padronizado a partir dos campos extraídos do CSV."""
    chave = f"{banco}:{filepath.name}:{data}:{valor}:{descricao}"
    hash_doc = hashlib.sha256(chave.encode()).hexdigest()

    return Documento(
        tipo=TipoDocumento.CSV,
        nome_arquivo=filepath.name,
        hash_sha256=hash_doc,
        data_emissao=data,
        valor_total=Dinheiro(abs(valor)),
        valor_liquido=Dinheiro(abs(valor)),
        nome_emitente=descricao.upper().strip(),
        fonte_extracao=FonteExtracao.CSV,
        confidence_scores=[
            ConfidenceScore(1.0, "valor"),
            ConfidenceScore(1.0, "data"),
            ConfidenceScore(0.90, "descricao"),
        ],
        precisa_revisao=False,
        natureza_operacao=NaturezaLancamento.CREDITO if valor > 0 else NaturezaLancamento.DEBITO,
    )


def parse_data_br(texto: str) -> date:
    """Interpreta datas nos formatos DD/MM/YYYY, DD/MM/YY ou YYYY-MM-DD."""
    texto = texto.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data não reconhecida: {texto}")
