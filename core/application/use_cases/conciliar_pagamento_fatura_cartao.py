"""Use case: ConciliarPagamentoFaturaCartao — ADR 010, Fase 6, B6-3.

Concilia o lançamento agregado de pagamento de uma FaturaCartao contra
o extrato bancário — reaproveitando MotorConciliacao (Fase 5, sem
alteração) e LocalizarPagamentoFaturaCartaoUseCase (B6-1, sem
duplicar a lógica de localização).

Ponto arquitetural central (Gate B6-3): este use case NÃO filtra
compras — ele constrói um conjunto de candidatos que, por contrato,
contém somente o lançamento de pagamento (`candidatos = [lancamento]`,
sempre uma lista de um elemento). Isso é estruturalmente mais forte do
que repetir o filtro de B6-2: não há filtro a esquecer ou a burlar,
porque nunca existiu outra coisa na lista para começar.

Escopo desta etapa (B6-3): apenas a conciliação em memória. NÃO
persiste vínculo (`pagamentos_faturas_cartao` é B6-5/6/14). NÃO
publica `PagamentoCartaoIdentificado` (é B6-8). NÃO altera
MotorConciliacao, core/cli.py, Lancamento, FITID/Camada 1, nem cria
migration.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from core.application.use_cases.localizar_pagamento_fatura_cartao import (
    LocalizarPagamentoFaturaCartaoUseCase,
)
from core.domain.entities import ConciliacaoItem
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.rule_engine.motor_conciliacao import MotorConciliacao


@dataclass
class ResultadoConciliacaoPagamentoFatura:
    fatura_id: UUID
    lancamento_pagamento_id: UUID
    item: ConciliacaoItem


class ConciliarPagamentoFaturaCartaoUseCase:
    """B6-3 — concilia o pagamento agregado de uma fatura, sozinho.

    Reaproveita LocalizarPagamentoFaturaCartaoUseCase (B6-1) para obter
    o lançamento — herda dele FaturaNaoEncontradaError e
    PagamentoNaoGeradoError, sem redefinir exceções.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        motor: MotorConciliacao | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._motor = motor or MotorConciliacao()
        self._localizar = LocalizarPagamentoFaturaCartaoUseCase(session_factory)

    def executar(
        self, fatura_id: UUID, data_inicio: date, data_fim: date,
    ) -> ResultadoConciliacaoPagamentoFatura:
        localizado = self._localizar.executar(fatura_id)
        lancamento_pagamento = localizado.lancamento_pagamento

        with UnitOfWork(self._session_factory) as uow:
            transacoes = uow.transacoes_bancarias.listar_por_empresa_e_periodo(
                lancamento_pagamento.empresa_id, data_inicio, data_fim,
            )

        # Contrato central de B6-3: candidatos é sempre uma lista de um
        # único elemento — o lançamento de pagamento. Não é um filtro
        # aplicado sobre uma lista maior (isso seria repetir B6-2); é a
        # única coisa que este use case constrói, por definição.
        candidatos = [lancamento_pagamento]

        relatorio = self._motor.conciliar(
            lancamentos=candidatos,
            transacoes=transacoes,
            empresa_id=lancamento_pagamento.empresa_id,
            periodo_inicio=data_inicio,
            periodo_fim=data_fim,
        )

        # relatorio.itens pode conter mais de 1 item se houver outras
        # transações no período (uma por transação, na Fase 1 do motor)
        # — localizamos explicitamente o item do nosso lançamento, nunca
        # assumimos itens[0].
        item = next(
            i for i in relatorio.itens
            if i.lancamento_id == localizado.lancamento_pagamento_id
        )

        return ResultadoConciliacaoPagamentoFatura(
            fatura_id=fatura_id,
            lancamento_pagamento_id=localizado.lancamento_pagamento_id,
            item=item,
        )
