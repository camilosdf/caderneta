"""Use case: LocalizarPagamentoFaturaCartao — ADR 010, Fase 6, B6-1.

Localiza o Lancamento agregado de pagamento de uma FaturaCartao,
exclusivamente pela identidade determinística estabelecida em B6-0
(core/application/use_cases/gerar_lancamentos_fatura_cartao.py).

Guardrail (Gate B6-1, autorização explícita): não localizar por
heurística (categoria/valor/data) — apenas pela identidade
determinística. Ver ADR 010, "Decisão arquitetural registrada —
Identidade do lançamento de pagamento": buscar por heurística
reintroduziria exatamente a ambiguidade que a Fase 6 existe para
eliminar.

Não altera Lancamento, LancamentoORM, nem os métodos da Fase 3.
Somente leitura — não persiste nada.
"""

from dataclasses import dataclass
from uuid import UUID

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    FaturaNaoEncontradaError,
    calcular_id_lancamento_pagamento,
)
from core.domain.entities import Lancamento
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork


class PagamentoNaoGeradoError(Exception):
    """A fatura existe, mas B6-0 ainda não gerou/persistiu o lançamento
    de pagamento (id determinístico não encontrado em `lancamentos`)."""


@dataclass
class ResultadoLocalizacaoPagamento:
    fatura_id: UUID
    lancamento_pagamento_id: UUID
    lancamento_pagamento: Lancamento


class LocalizarPagamentoFaturaCartaoUseCase:
    """B6-1 — localiza o Lancamento de pagamento de uma fatura, somente
    por identidade determinística (nunca por categoria/valor/data)."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def executar(self, fatura_id: UUID) -> ResultadoLocalizacaoPagamento:
        id_pagamento = calcular_id_lancamento_pagamento(fatura_id)

        with UnitOfWork(self._session_factory) as uow:
            fatura = uow.faturas_cartao.buscar_por_id(fatura_id)
            if fatura is None:
                raise FaturaNaoEncontradaError(f"Fatura {fatura_id} não encontrada.")

            lancamento_pagamento = uow.lancamentos.buscar_por_id(id_pagamento)
            if lancamento_pagamento is None:
                raise PagamentoNaoGeradoError(
                    f"Fatura {fatura_id} não tem lançamento de pagamento "
                    f"gerado ainda — execute B6-0 "
                    f"(GerarLancamentosFaturaCartaoUseCase) primeiro."
                )

        return ResultadoLocalizacaoPagamento(
            fatura_id=fatura_id,
            lancamento_pagamento_id=id_pagamento,
            lancamento_pagamento=lancamento_pagamento,
        )
