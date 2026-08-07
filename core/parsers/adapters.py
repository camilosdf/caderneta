"""Adaptadores e Protocol para uniformizar a interface dos parsers.

Todos os parsers concretos implementam ParserProtocol:
    def parsear(self, filepath: Path) -> Iterator[Documento]

Isso permite que ParserFactory e ProcessarDocumentoUseCase
trabalhem com qualquer parser sem conhecer sua implementação.
"""

from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from core.domain.entities import Documento


@runtime_checkable
class ParserProtocol(Protocol):
    """Interface comum a todos os parsers do Caderneta."""

    def parsear(self, filepath: Path) -> Iterator[Documento]:
        """Parseia um arquivo e gera um Documento por transação/nota."""
        ...


class NFeParser:
    """Adaptador que envolve parsear_nfe() na interface ParserProtocol.

    parsear_nfe() retorna um único Documento (NF-e é um documento único).
    Este adaptador o expõe como Iterator para uniformidade com OFX/CSV.
    """

    def parsear(self, filepath: Path) -> Iterator[Documento]:
        from core.parsers.nfe.xml import parsear_nfe
        yield parsear_nfe(filepath)


class CSVParser:
    """Adaptador que envolve parsear_csv() na interface ParserProtocol.

    parsear_csv() já retorna Iterator[Documento] — este adaptador
    apenas padroniza o empacotamento e isola a detecção de banco.
    """

    def parsear(self, filepath: Path) -> Iterator[Documento]:
        from core.parsers.csv import parsear_csv
        yield from parsear_csv(filepath)
