"""Use case: PersistirConciliacaoPagamentoFaturaCartao — ADR 010, Fase 6, B6-5/B6-6/B6-7/B6-8/B6-14.

Consome o resultado em memória de ConciliarPagamentoFaturaCartaoUseCase
(B6-3, inalterado — reaproveitado por composição, não por herança nem
modificação) e persiste o vínculo Fatura <-> Lançamento <-> Transação
quando a conciliação resultou em CONCILIADO.

Guardrails (Gates B6-5, B6-7 e B6-8, autorização explícita):
  - B6-3 não é alterado — este é um use case NOVO e SEPARADO que chama
    B6-3 e usa seu resultado, nunca modifica sua lógica interna.
  - Atomicidade: cálculo do resultado (B6-3, somente leitura),
    persistência do vínculo (B6-5) e registro de auditoria (B6-7)
    ocorrem com o COMMIT acontecendo uma única vez, na mesma
    UnitOfWork da persistência.
  - Concorrência: a garantia real é da constraint UNIQUE no banco
    (ver PagamentoFaturaCartaoRepository.persistir_conciliacao) — este
    use case apenas propaga o resultado (persistido/não persistido),
    não decide o mecanismo de proteção.
  - B6-7 (auditoria): registra TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO
    na hash chain SOMENTE quando persistido=True.
  - B6-8 (evento): publica PagamentoCartaoIdentificado (EventBusPort)
    SOMENTE quando persistido=True — mesmo critério de B6-7, mesmo
    padrão de injeção opcional já usado em ProcessarFaturaCartaoUseCase
    (Fase 4): event_bus injetado via construtor; sem ele, nada é
    publicado (comportamento idêntico ao anterior a B6-8, preservado).
    Publicado DEPOIS do commit da UnitOfWork — mesmo padrão de Fase 4
    (evento de domínio não é uma escrita transacional, é notificação
    pós-fato consumado).
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from core.application.use_cases.conciliar_pagamento_fatura_cartao import (
    ConciliarPagamentoFaturaCartaoUseCase,
)
from core.audit.chain import TipoEvento
from core.domain.entities import ConciliacaoItem, TipoConciliacao
from core.events.catalog import EventBusPort, PagamentoCartaoIdentificado
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork


@dataclass
class ResultadoPersistenciaConciliacao:
    fatura_id: UUID
    item: ConciliacaoItem
    persistido: bool
    motivo_nao_persistido: str | None = None
    auditoria_registrada: bool = False
    evento_publicado: bool = False


class PersistirConciliacaoPagamentoFaturaCartaoUseCase:
    """B6-5/B6-6/B6-14 — persiste o resultado de B6-3, quando CONCILIADO.

    Composição explícita de ConciliarPagamentoFaturaCartaoUseCase (B6-3)
    — nunca subclasse, nunca modifica seu comportamento.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        conciliar: ConciliarPagamentoFaturaCartaoUseCase | None = None,
        event_bus: EventBusPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._conciliar = conciliar or ConciliarPagamentoFaturaCartaoUseCase(session_factory)
        self._event_bus = event_bus

    def executar(
        self, fatura_id: UUID, data_inicio: date, data_fim: date, usuario: str = "sistema",
    ) -> ResultadoPersistenciaConciliacao:
        resultado = self._conciliar.executar(fatura_id, data_inicio, data_fim)
        item = resultado.item

        if item.status != TipoConciliacao.CONCILIADO:
            return ResultadoPersistenciaConciliacao(
                fatura_id=fatura_id,
                item=item,
                persistido=False,
                motivo_nao_persistido=(
                    f"status={item.status.value} — nada a persistir "
                    f"(só CONCILIADO gera vínculo)"
                ),
            )

        with UnitOfWork(self._session_factory) as uow:
            lancamento_pagamento = uow.lancamentos.buscar_por_id(
                resultado.lancamento_pagamento_id
            )
            persistido = uow.pagamentos_faturas_cartao.persistir_conciliacao(
                empresa_id=lancamento_pagamento.empresa_id,
                fatura_cartao_id=fatura_id,
                item=item,
            )

            auditoria_registrada = False
            if persistido:
                # B6-7 — registro de auditoria SOMENTE quando o vínculo
                # foi de fato persistido (fato consumado, não tentativa).
                # Mesma UnitOfWork/commit da persistência do vínculo —
                # atomicidade entre os dois, nunca em transação separada.
                uow.audit.registrar(
                    tipo=TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO,
                    payload={
                        "fatura_id": str(fatura_id),
                        "lancamento_id": str(item.lancamento_id),
                        "transacao_bancaria_id": str(item.transacao_bancaria_id),
                        "metodo_matching": item.metodo.value,
                        "score": str(item.score),
                        "status": item.status.value,
                    },
                    usuario=usuario,
                    empresa_id=str(lancamento_pagamento.empresa_id),
                    lancamento_id=str(item.lancamento_id),
                )
                auditoria_registrada = True
                uow.commit()
            # Se não persistido (conflito de UNIQUE), a inserção que
            # falhou já foi revertida via savepoint dentro do
            # repositório — nenhum commit necessário aqui, nenhuma
            # auditoria registrada (não é um fato consumado).

        # B6-8 — publicação em EventBusPort, DEPOIS do commit da
        # UnitOfWork (mesmo padrão de ProcessarFaturaCartaoUseCase,
        # Fase 4) — evento de domínio é notificação pós-fato consumado,
        # não parte da transação de escrita. Mesmo critério de B6-7:
        # só quando persistido=True. Sem event_bus injetado, nada é
        # publicado — comportamento idêntico ao anterior a B6-8.
        evento_publicado = False
        if persistido and self._event_bus is not None:
            self._event_bus.publicar(PagamentoCartaoIdentificado(
                fatura_id=str(fatura_id),
                lancamento_pagamento_id=str(item.lancamento_id),
                transacao_bancaria_id=str(item.transacao_bancaria_id),
                metodo_matching=item.metodo.value,
            ))
            evento_publicado = True

        return ResultadoPersistenciaConciliacao(
            fatura_id=fatura_id,
            item=item,
            persistido=persistido,
            motivo_nao_persistido=None if persistido else (
                "conflito de unicidade — fatura, lançamento ou transação "
                "já vinculados por outra execução (fronteira cross-call "
                "de B6-3, resolvida aqui pela UNIQUE do banco)"
            ),
            auditoria_registrada=auditoria_registrada,
            evento_publicado=evento_publicado,
        )
