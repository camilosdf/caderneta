"""ParserFactory — resolução de TipoDocumento → Parser.

Responsabilidade única: mapear um TipoDocumento para o parser correto.
Não sabe como cada parser funciona internamente — apenas registra e resolve.

Para adicionar um novo tipo:
    factory = ParserFactory()
    factory.registrar(TipoDocumento.BOLETO, BoletoParser())
"""

from core.domain.entities import TipoDocumento
from core.parsers.adapters import CSVParser, NFeParser, ParserProtocol
from core.parsers.ofx import OFXParser


class ParserNaoSuportadoError(Exception):
    pass


class ParserFactory:
    """Factory que resolve TipoDocumento → ParserProtocol."""

    def __init__(self) -> None:
        self._parsers: dict[TipoDocumento, ParserProtocol] = {
            TipoDocumento.NFE_XML: NFeParser(),
            TipoDocumento.OFX:     OFXParser(),
            TipoDocumento.CSV:     CSVParser(),
        }

    def obter(self, tipo: TipoDocumento) -> ParserProtocol:
        """Retorna o parser registrado para o tipo de documento.

        Raises:
            ParserNaoSuportadoError: se nenhum parser estiver registrado
                para o tipo informado.
        """
        parser = self._parsers.get(tipo)
        if parser is None:
            raise ParserNaoSuportadoError(
                f"Nenhum parser registrado para: {tipo.value}. "
                f"Tipos suportados: {[t.value for t in self._parsers]}"
            )
        return parser

    def registrar(self, tipo: TipoDocumento, parser: ParserProtocol) -> None:
        """Registra ou substitui o parser de um tipo de documento."""
        self._parsers[tipo] = parser

    @property
    def tipos_suportados(self) -> list[TipoDocumento]:
        return list(self._parsers.keys())
