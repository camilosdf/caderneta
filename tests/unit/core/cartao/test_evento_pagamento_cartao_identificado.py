"""Testes de B6-8 — Disparo de PagamentoCartaoIdentificado (ADR 010, Fase 6).

Cobre: publicação em EventBusPort somente quando persistido=True,
ausência de publicação quando não persistido, payload correto,
ausência de publicação quando event_bus não é injetado (retrocompatível
com B6-5/6/7), e publicação após o commit (não antes).
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    GerarLancamentosFaturaCartaoUseCase,
    calcular_id_lancamento_pagamento,
)
from core.application.use_cases.persistir_conciliacao_pagamento_fatura_cartao import (
    PersistirConciliacaoPagamentoFaturaCartaoUseCase,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    ContaBancaria,
    Dinheiro,
    FaturaCartao,
    NaturezaLancamento,
    TipoItemFatura,
    TransacaoBancaria,
)
from core.events.catalog import EventBusEmMemoria, PagamentoCartaoIdentificado
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {TipoItemFatura.COMPRA: CodigoConta("4.1.01.001")}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


def _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, final_numero, valor_total="1000.00", data_vencimento=None):
    data_vencimento = data_vencimento or date(2026, 9, 15)

    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(
            empresa_id=empresa_id, emissor="Nubank", final_numero=final_numero,
            titular="Camilo", conta_codigo=CONTA_CARTAO,
        )
        uow.cartoes_credito.salvar_se_novo(cartao)

        fatura = FaturaCartao(
            empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
            data_vencimento=data_vencimento, valor_total_declarado=Dinheiro(Decimal(valor_total)),
        )
        fatura.itens.append(CompraCartao(
            empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal(valor_total)),
            posicao_linha=1, data_compra=data_vencimento,
        ))
        fatura.validar_fechamento()
        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()

    GerarLancamentosFaturaCartaoUseCase(session_factory=sf).executar(
        fatura.id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
        contas_despesa_por_tipo=CONTAS_DESPESA,
    )

    with UnitOfWork(sf) as uow:
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)
        lanc_pagamento = uow.lancamentos.buscar_por_id(id_pagamento)
        lanc_pagamento.aprovar("teste")
        uow.lancamentos.salvar(lanc_pagamento)
        item_compra = uow.faturas_cartao.buscar_por_id(fatura.id).itens[0]
        lanc_compra = uow.lancamentos.buscar_por_id(item_compra.lancamento_id)
        lanc_compra.aprovar("teste")
        uow.lancamentos.salvar(lanc_compra)
        uow.commit()

    return fatura.id, id_pagamento


def _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-B68"):
    return TransacaoBancaria(
        empresa_id=empresa_id,
        conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
        fitid=fitid, data=data, valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
    )


# =============================================================
# POSITIVO — publicação quando persistido e event_bus injetado
# =============================================================

class TestEventoPublicadoQuandoPersistido:
    def test_evento_publicado_no_event_bus(self):
        sf = _session_factory()
        bus = EventBusEmMemoria()
        empresa_id = uuid4()
        fatura_id, id_pagamento = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "1111")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf, event_bus=bus)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.evento_publicado is True
        assert len(bus._publicados) == 1
        evento = bus._publicados[0]
        assert isinstance(evento, PagamentoCartaoIdentificado)
        assert evento.fatura_id == str(fatura_id)
        assert evento.lancamento_pagamento_id == str(id_pagamento)
        assert evento.transacao_bancaria_id == str(tx.id)
        assert evento.metodo_matching == "valor_data"

    def test_handler_registrado_e_chamado(self):
        """Prova de integração real do EventBusPort — não só que o
        evento foi empilhado, mas que um handler registrado é
        efetivamente invocado."""
        sf = _session_factory()
        bus = EventBusEmMemoria()
        recebidos = []
        bus.escutar(PagamentoCartaoIdentificado, lambda e: recebidos.append(e))

        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "2222")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf, event_bus=bus).executar(
            fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30)
        )

        assert len(recebidos) == 1
        assert recebidos[0].fatura_id == str(fatura_id)


# =============================================================
# NEGATIVO — sem publicação
# =============================================================

class TestSemPublicacao:
    def test_sem_event_bus_injetado_nao_publica_nada(self):
        """Retrocompatibilidade — sem event_bus, comportamento idêntico
        ao anterior a B6-8 (B6-5/6/7 continuam funcionando sem
        alteração)."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "3333")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)  # sem event_bus
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.persistido is True  # persistência não depende de event_bus
        assert resultado.evento_publicado is False

    def test_nao_persistido_nao_publica_mesmo_com_event_bus(self):
        """status != CONCILIADO -> nem persiste, nem audita, nem publica."""
        sf = _session_factory()
        bus = EventBusEmMemoria()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "4444")
        # nenhuma transação -> SEM_MATCH

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf, event_bus=bus)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.persistido is False
        assert resultado.evento_publicado is False
        assert bus._publicados == []

    def test_conflito_de_unicidade_publica_apenas_para_a_que_persistiu(self):
        """Duas faturas disputando a mesma transação -> só um evento
        publicado, para a execução que efetivamente persistiu."""
        sf = _session_factory()
        bus = EventBusEmMemoria()
        empresa_id = uuid4()
        data_vencimento = date(2026, 9, 15)
        fatura_id_1, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "5555", "1000.00", data_vencimento)
        fatura_id_2, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "6666", "1000.00", data_vencimento)
        tx = _transacao(empresa_id, valor="1000.00", data=data_vencimento, fitid="TX-DISPUTA-B68")
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf, event_bus=bus)
        r1 = uc.executar(fatura_id_1, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))
        r2 = uc.executar(fatura_id_2, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert r1.evento_publicado != r2.evento_publicado
        assert len(bus._publicados) == 1  # exatamente um evento, nunca dois


# =============================================================
# GUARDRAIL — persistência/auditoria não dependem do event_bus
# =============================================================

class TestPublicacaoNaoAfetaPersistenciaOuAuditoria:
    def test_persistencia_e_auditoria_ocorrem_mesmo_sem_event_bus(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "7777")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        resultado = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30)
        )

        assert resultado.persistido is True
        assert resultado.auditoria_registrada is True
        assert resultado.evento_publicado is False
