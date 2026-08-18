"""Use case: GerarLancamentosFaturaCartao — ADR 010, Fase 6, B6-0.

Orquestra a geração e persistência dos lançamentos de compra (D7) e
pagamento (D8) a partir de uma FaturaCartao já persistida e FECHADA —
elo que faltava entre a Fase 3 (regras contábeis, testadas em isolado)
e o restante do pipeline (achado da Etapa 6.1/matriz formal de
autorização da Fase 6).

Guardrails (Gate B6-0, autorização explícita):
  - Não altera Lancamento nem LancamentoORM.
  - Não altera a lógica de LancamentoService.construir_lancamento_*
    (Fase 3) — este use case apenas os chama e persiste o resultado.
  - FaturaCartao com status_fechamento != FECHADA não gera lançamentos.
  - Idempotente por REUTILIZAÇÃO, não apenas ausência de duplicata:
    reprocessar a mesma fatura retorna os mesmos ids de lançamento.
  - Transacional: geração + persistência + atualização de
    CompraCartao.lancamento_id ocorrem na mesma UnitOfWork. Falha em
    qualquer item reverte tudo (rollback automático da UnitOfWork).

Idempotência do lançamento de pagamento (sem migration — ADR 010 não
tem campo para "lancamento_pagamento_id" em FaturaCartao/ORM):
  o id do Lancamento de pagamento é derivado deterministicamente de
  fatura.id via uuid5 — nunca uuid4 aleatório. Reexecutar produz o
  mesmo id, que é buscado antes de qualquer nova criação. Essa escolha
  é feita inteiramente aqui (mutação de `.id` após a construção via
  LancamentoService) — LancamentoService nunca é alterado.
"""

from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.entities import (
    CodigoConta,
    StatusFechamentoFatura,
    TipoItemFatura,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.rule_engine.lancamento_service import LancamentoService

_NAMESPACE_PAGAMENTO_FATURA = uuid5(NAMESPACE_URL, "caderneta:adr010:pagamento-fatura-cartao")


def calcular_id_lancamento_pagamento(fatura_id: UUID) -> UUID:
    """Id determinístico do Lancamento de pagamento de uma fatura.

    Mesma fatura_id sempre produz o mesmo id — usado como chave de
    idempotência (B6-0) e como forma exclusiva de localizar o
    lançamento de pagamento (B6-1). Nunca localizar por heurística
    (categoria/valor/data) — ver ADR 010, "Decisão arquitetural
    registrada — Identidade do lançamento de pagamento".

    Pública (não prefixada com _) porque é reutilizada fora deste
    módulo, por localizar_pagamento_fatura_cartao.py (B6-1) e por
    fases futuras que precisem da mesma identidade.
    """
    return uuid5(_NAMESPACE_PAGAMENTO_FATURA, str(fatura_id))


class FaturaNaoEncontradaError(Exception):
    """Fatura não existe (id inválido ou de outra empresa)."""


class FaturaNaoFechadaError(Exception):
    """FaturaCartao.status_fechamento != FECHADA — não gera lançamentos
    automaticamente (mesmo princípio de D5 já aplicado na Fase 2)."""


class ContaDespesaNaoMapeadaError(Exception):
    """Não há conta de despesa mapeada para o tipo de item."""


@dataclass
class ResultadoGeracaoLancamentos:
    fatura_id: UUID
    lancamento_pagamento_id: UUID
    lancamentos_compra_ids: list[UUID] = field(default_factory=list)
    ja_processado: bool = False


class GerarLancamentosFaturaCartaoUseCase:
    """B6-0 — orquestra LancamentoService para uma FaturaCartao FECHADA."""

    def __init__(
        self,
        session_factory: SessionFactory,
        lancamento_service: LancamentoService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lancamento_service = lancamento_service or LancamentoService()

    def executar(
        self,
        fatura_id: UUID,
        conta_cartao: CodigoConta,
        conta_banco: CodigoConta,
        contas_despesa_por_tipo: dict[TipoItemFatura, CodigoConta],
    ) -> ResultadoGeracaoLancamentos:
        with UnitOfWork(self._session_factory) as uow:
            fatura = uow.faturas_cartao.buscar_por_id(fatura_id)
            if fatura is None:
                raise FaturaNaoEncontradaError(f"Fatura {fatura_id} não encontrada.")

            if fatura.status_fechamento != StatusFechamentoFatura.FECHADA:
                raise FaturaNaoFechadaError(
                    f"Fatura {fatura_id} tem status "
                    f"'{fatura.status_fechamento.value}' — lançamentos só "
                    f"são gerados para faturas FECHADA (D5)."
                )

            id_pagamento = calcular_id_lancamento_pagamento(fatura.id)
            pagamento_existente = uow.lancamentos.buscar_por_id(id_pagamento)
            todas_compras_ja_vinculadas = all(
                item.lancamento_id is not None for item in fatura.itens
            )

            if pagamento_existente is not None and todas_compras_ja_vinculadas:
                # Idempotência por reutilização (não apenas ausência de
                # duplicata) — mesmo estado retornado, nada é regravado.
                uow.commit()
                return ResultadoGeracaoLancamentos(
                    fatura_id=fatura.id,
                    lancamento_pagamento_id=id_pagamento,
                    lancamentos_compra_ids=[item.lancamento_id for item in fatura.itens],
                    ja_processado=True,
                )

            lancamentos_compra_ids: list[UUID] = []

            for item in fatura.itens:
                if item.lancamento_id is not None:
                    # Item já processado em execução anterior (reuso parcial)
                    lancamentos_compra_ids.append(item.lancamento_id)
                    continue

                conta_despesa = contas_despesa_por_tipo.get(item.tipo)
                if conta_despesa is None:
                    raise ContaDespesaNaoMapeadaError(
                        f"Nenhuma conta de despesa mapeada para o tipo "
                        f"'{item.tipo.value}' (item {item.id})."
                    )

                lancamento_compra = self._lancamento_service.construir_lancamento_compra_cartao(
                    item, conta_despesa=conta_despesa, conta_cartao=conta_cartao,
                )
                uow.lancamentos.salvar(lancamento_compra)
                item.lancamento_id = lancamento_compra.id
                lancamentos_compra_ids.append(lancamento_compra.id)

            if pagamento_existente is None:
                lancamento_pagamento = self._lancamento_service.construir_lancamento_pagamento_fatura(
                    fatura, conta_cartao=conta_cartao, conta_banco=conta_banco,
                )
                # Id determinístico atribuído aqui — fora de LancamentoService,
                # que nunca decide identidade (guardrail B6-0).
                lancamento_pagamento.id = id_pagamento
                uow.lancamentos.salvar(lancamento_pagamento)

            uow.faturas_cartao.atualizar_lancamento_ids_dos_itens(fatura)

            uow.commit()

            return ResultadoGeracaoLancamentos(
                fatura_id=fatura.id,
                lancamento_pagamento_id=id_pagamento,
                lancamentos_compra_ids=lancamentos_compra_ids,
                ja_processado=False,
            )
