"""Testes de B6-3 — ConciliarPagamentoFaturaCartaoUseCase (ADR 010, Fase 6).

7 testes (1a, 1b, 2, 3, 4, 5, 6), conforme plano de implementação
aprovado. Cobrem, separadamente: o contrato estrutural (candidato
único entregue ao motor) e o resultado funcional (conciliado/pendente),
mais os negativos e a regressão do cenário de empate pelo caminho
estreito (sem depender do CLI/B6-2).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from core.application.use_cases.conciliar_pagamento_fatura_cartao import (
    ConciliarPagamentoFaturaCartaoUseCase,
)
from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    FaturaNaoEncontradaError,
    GerarLancamentosFaturaCartaoUseCase,
    calcular_id_lancamento_pagamento,
)
from core.application.use_cases.localizar_pagamento_fatura_cartao import (
    PagamentoNaoGeradoError,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    ContaBancaria,
    Dinheiro,
    FaturaCartao,
    MetodoMatching,
    NaturezaLancamento,
    TipoConciliacao,
    TipoItemFatura,
    TransacaoBancaria,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.rule_engine.motor_conciliacao import MotorConciliacao

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {TipoItemFatura.COMPRA: CodigoConta("4.1.01.001")}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


def _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1, data_compra=None, data_vencimento=None):
    data_vencimento = data_vencimento or date(2026, 9, 15)
    data_compra = data_compra or data_vencimento

    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(empresa_id=empresa_id, emissor="Nubank", final_numero="1234", titular="Camilo", conta_codigo=CONTA_CARTAO)
        uow.cartoes_credito.salvar_se_novo(cartao)

        valor_item = Decimal(valor_total) / n_itens
        fatura = FaturaCartao(
            empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
            data_vencimento=data_vencimento, valor_total_declarado=Dinheiro(Decimal(valor_total)),
        )
        for _ in range(n_itens):
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA, valor=Dinheiro(valor_item),
                posicao_linha=len(fatura.itens) + 1, data_compra=data_compra,
            ))
        fatura.validar_fechamento()
        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()

    GerarLancamentosFaturaCartaoUseCase(session_factory=sf).executar(
        fatura.id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
        contas_despesa_por_tipo=CONTAS_DESPESA,
    )

    with UnitOfWork(sf) as uow:
        fatura_recarregada = uow.faturas_cartao.buscar_por_id(fatura.id)
        for item in fatura_recarregada.itens:
            lanc = uow.lancamentos.buscar_por_id(item.lancamento_id)
            lanc.aprovar("teste")
            uow.lancamentos.salvar(lanc)
        lanc_pagamento = uow.lancamentos.buscar_por_id(calcular_id_lancamento_pagamento(fatura.id))
        lanc_pagamento.aprovar("teste")
        uow.lancamentos.salvar(lanc_pagamento)
        uow.commit()

    return fatura_recarregada


def _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-001"):
    return TransacaoBancaria(
        empresa_id=empresa_id,
        conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
        fitid=fitid, data=data, valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
    )


def _salvar_transacao(sf, tx):
    with UnitOfWork(sf) as uow:
        uow.transacoes_bancarias.salvar_se_nova(tx)
        uow.commit()


# =============================================================
# 1a — contrato estrutural: candidato único entregue ao motor
# =============================================================

class TestContratoCandidatoUnico:
    def test_motor_recebe_lista_com_apenas_o_lancamento_de_pagamento(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=3)
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)
        tx = _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15))
        _salvar_transacao(sf, tx)

        motor_spy = MagicMock(wraps=MotorConciliacao())
        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf, motor=motor_spy)
        uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert motor_spy.conciliar.called
        kwargs = motor_spy.conciliar.call_args.kwargs
        lancamentos_recebidos = kwargs["lancamentos"]

        assert len(lancamentos_recebidos) == 1
        assert lancamentos_recebidos[0].id == id_pagamento


# =============================================================
# 1b — resultado funcional: conciliado com transação compatível
# =============================================================

class TestResultadoFuncionalConciliado:
    def test_resultado_conciliado_com_transacao_compativel(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=2)
        tx = _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15))
        _salvar_transacao(sf, tx)

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.item.status == TipoConciliacao.CONCILIADO
        assert resultado.item.metodo == MetodoMatching.VALOR_DATA
        assert resultado.item.transacao_bancaria_id == tx.id


# =============================================================
# 2 — sem transação correspondente
# =============================================================

class TestSemTransacaoCorrespondente:
    def test_sem_transacao_no_periodo_retorna_pendente_sem_match(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="500.00", n_itens=1)
        # nenhuma transação persistida

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.item.status == TipoConciliacao.PENDENTE
        assert resultado.item.metodo == MetodoMatching.SEM_MATCH
        assert resultado.item.transacao_bancaria_id is None


# =============================================================
# 3 — fatura sem B6-0 executado
# =============================================================

class TestFaturaSemPagamentoGerado:
    def test_fatura_sem_b6_0_levanta_pagamento_nao_gerado(self):
        sf = _session_factory()
        empresa_id = uuid4()
        with UnitOfWork(sf) as uow:
            cartao = CartaoCredito(empresa_id=empresa_id, emissor="Nubank", final_numero="1234", titular="Camilo", conta_codigo=CONTA_CARTAO)
            uow.cartoes_credito.salvar_se_novo(cartao)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
                valor_total_declarado=Dinheiro(Decimal("100.00")),
            )
            fatura.itens.append(CompraCartao(empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("100.00")), posicao_linha=1))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(PagamentoNaoGeradoError):
            uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

    def test_fatura_inexistente_levanta_erro(self):
        sf = _session_factory()
        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(FaturaNaoEncontradaError):
            uc.executar(uuid4(), data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))


# =============================================================
# 4 — compra nunca é candidata, mesmo com coincidência total
# =============================================================

class TestCompraNuncaCandidata:
    def test_compra_com_valor_data_coincidentes_nao_aparece_na_lista_entregue_ao_motor(self):
        sf = _session_factory()
        empresa_id = uuid4()
        # fatura de 1 item -> compra e pagamento com o MESMO valor e MESMA data
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1)
        id_compra = fatura.itens[0].lancamento_id
        tx = _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15))
        _salvar_transacao(sf, tx)

        motor_spy = MagicMock(wraps=MotorConciliacao())
        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf, motor=motor_spy)
        uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        lancamentos_recebidos = motor_spy.conciliar.call_args.kwargs["lancamentos"]
        ids_recebidos = {lanc.id for lanc in lancamentos_recebidos}

        assert id_compra not in ids_recebidos  # nunca chega ao motor, nem por engano


# =============================================================
# 5 — regressão do empate 1000/1000/1000, caminho estreito
# =============================================================

class TestEmpateViaUseCaseEstreito:
    def test_empate_1000_1000_1000_conciliado_e_o_pagamento_nao_a_compra(self):
        """Mesma garantia do teste de B6-2, agora sem depender do CLI —
        prova que a proteção não é acidental ao caminho genérico."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1)
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)
        tx = _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15))
        _salvar_transacao(sf, tx)

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.item.status == TipoConciliacao.CONCILIADO
        assert resultado.item.lancamento_id == id_pagamento

    def test_localiza_item_correto_mesmo_com_outras_transacoes_no_periodo(self):
        """Ruído: outras transações no mesmo período não devem confundir
        a seleção do item correspondente ao nosso lançamento."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1)
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)

        tx_alheia = _transacao(empresa_id, valor="50.00", data=date(2026, 9, 5), fitid="TX-ALHEIA")
        tx_pagamento = _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-PAGAMENTO")
        _salvar_transacao(sf, tx_alheia)
        _salvar_transacao(sf, tx_pagamento)

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.item.lancamento_id == id_pagamento
        assert resultado.item.status == TipoConciliacao.CONCILIADO
        assert resultado.item.transacao_bancaria_id == tx_pagamento.id


# =============================================================
# 6 — motor chamado sem parâmetro novo (assinatura já existente na Fase 5)
# =============================================================

class TestAssinaturaDoMotorInalterada:
    def test_conciliar_chamado_com_parametros_ja_existentes_desde_fase_5(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="300.00", n_itens=1)
        tx = _transacao(empresa_id, valor="300.00", data=date(2026, 9, 15))
        _salvar_transacao(sf, tx)

        motor_spy = MagicMock(wraps=MotorConciliacao())
        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf, motor=motor_spy)
        uc.executar(fatura.id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        kwargs = motor_spy.conciliar.call_args.kwargs
        parametros_esperados = {
            "lancamentos", "transacoes", "empresa_id", "periodo_inicio", "periodo_fim",
        }
        # B6-3 não introduz nenhum parâmetro além dos já existentes desde
        # a Fase 5 (fitids_por_lancamento é opcional e nem é passado aqui).
        assert set(kwargs.keys()) <= parametros_esperados | {"fitids_por_lancamento"}
        assert "fitids_por_lancamento" not in kwargs  # nem sequer usado neste caminho
