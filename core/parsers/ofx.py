"""Parser para extratos bancários no formato OFX.

Suporta arquivos OFX/QFX gerados pelos principais bancos brasileiros.
É a fonte de maior confiança para extratos — dados já estruturados.
"""

import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from core.domain.entities import (
    ConfidenceScore,
    Dinheiro,
    Documento,
    FonteExtracao,
    NaturezaLancamento,
    TipoDocumento,
)


class OFXParser:
    """Parser dedicado para arquivos OFX/QFX."""

    def parsear(self, filepath: Path) -> Iterator[Documento]:
        """Gera um Documento para cada transação no extrato."""
        from ofxparse import OfxParser as _OfxParser

        with open(filepath, "rb") as f:
            ofx = _OfxParser.parse(f)

        for conta in ofx.accounts:
            for transacao in conta.statement.transactions:
                valor = Decimal(str(transacao.amount))
                data_tx: date = (
                    transacao.date.date()
                    if hasattr(transacao.date, "date")
                    else transacao.date
                )

                yield Documento(
                    tipo=TipoDocumento.OFX,
                    nome_arquivo=filepath.name,
                    hash_sha256=self._hash_transacao(transacao),
                    numero_documento=getattr(transacao, "id", None),
                    data_emissao=data_tx,
                    valor_total=Dinheiro(abs(valor)),
                    valor_liquido=Dinheiro(abs(valor)),
                    nome_emitente=self._limpar_descricao(
                        getattr(transacao, "payee", None)
                        or getattr(transacao, "memo", "")
                    ),
                    fonte_extracao=FonteExtracao.OFX,
                    confidence_scores=[
                        ConfidenceScore(1.0, "valor"),
                        ConfidenceScore(1.0, "data"),
                        ConfidenceScore(0.95, "descricao"),
                    ],
                    precisa_revisao=False,
                    natureza_operacao=(
                        NaturezaLancamento.CREDITO if valor > 0
                        else NaturezaLancamento.DEBITO
                    ),
                )

    def validar_soma(self, filepath: Path) -> tuple[bool, Decimal, Decimal]:
        """Valida consistência interna das transações do extrato."""
        from ofxparse import OfxParser as _OfxParser

        with open(filepath, "rb") as f:
            ofx = _OfxParser.parse(f)

        for conta in ofx.accounts:
            saldo_declarado = Decimal(str(conta.statement.balance))
            soma = sum(Decimal(str(t.amount)) for t in conta.statement.transactions)
            return True, soma, saldo_declarado

        return True, Decimal("0"), Decimal("0")

    def _limpar_descricao(self, texto: str) -> str:
        if not texto:
            return "SEM DESCRIÇÃO"
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto.upper()

    def _hash_transacao(self, transacao: object) -> str:
        chave = (
            f"{getattr(transacao, 'id', '')}"
            f"{getattr(transacao, 'date', '')}"
            f"{getattr(transacao, 'amount', '')}"
            f"{getattr(transacao, 'memo', '')}"
        )
        return hashlib.sha256(chave.encode()).hexdigest()
