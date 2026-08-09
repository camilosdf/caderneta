"""BankStatementPort — contrato para fontes de extrato bancário (Etapa 8.1).

Define a interface que qualquer fonte de extrato deve satisfazer para
alimentar o Motor de Conciliação. O core define o contrato; a
infraestrutura implementa.

Implementações planejadas:
  - OFXBankStatementAdapter: lê arquivos OFX/QFX (Etapa 8, implementado)
  - OpenFinanceAdapter: API Open Finance BR (Fase 2, apenas Port agora)

O Motor de Conciliação (MotorConciliacao) nunca sabe se está lendo OFX
ou Open Finance — recebe apenas uma lista de TransacaoBancaria.
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from core.domain.entities import ContaBancaria, TransacaoBancaria


@runtime_checkable
class BankStatementPort(Protocol):
    """Contrato de fonte de extrato bancário.

    Responsabilidade única: converter uma fonte externa (arquivo OFX,
    API Open Finance, etc.) em uma lista de TransacaoBancaria do domínio.
    """

    def importar(
        self,
        fonte: Path | str,
        empresa_id,
        id_importacao: str,
    ) -> list[TransacaoBancaria]:
        """Importa transações bancárias de uma fonte externa.

        Args:
            fonte: caminho do arquivo (OFX) ou identificador da fonte
                   (conta Open Finance, URL, etc.).
            empresa_id: UUID da empresa dona das transações.
            id_importacao: identificador único desta importação —
                           permite detectar reimportações do mesmo
                           extrato (idempotência).

        Returns:
            Lista de TransacaoBancaria. O caller é responsável por
            garantir idempotência antes de persistir (checar
            chave_idempotencia() de cada item).
        """
        ...

    def detectar_conta(self, fonte: Path | str) -> ContaBancaria | None:
        """Tenta extrair a ContaBancaria da fonte sem importar tudo.

        Útil para confirmar com o usuário qual conta está sendo importada
        antes de processar o arquivo inteiro. Retorna None se não for
        possível determinar sem processar.
        """
        ...
