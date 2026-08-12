"""Testes de B6-1 — LocalizarPagamentoFaturaCartaoUseCase (ADR 010, Fase 6).

Cobre: localização positiva (após B6-0), erro quando B6-0 ainda não
rodou, erro de fatura inexistente, e — o ponto central do guardrail de
B6-1 — que a localização usa exclusivamente a identidade determinística,
nunca heurística por categoria/valor/data.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    FaturaNaoEncontradaError,
    GerarLancamentosFaturaCartaoUseCase,
    calcular_id_lancamento_pagamento,
)
from core.application.use_cases.localizar_pagamento_fatura_cartao import (
    LocalizarPagamentoFaturaCartaoUseCase,
    PagamentoNaoGeradoError,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    Dinheiro,
    FaturaCartao,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    TipoItemFatura,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {TipoItemFatura.COMPRA: CodigoConta("4.1.01.001")}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


def _fatura_fechada_persistida(sf: SessionFactory, empresa_id, valor_total="150.00", n_itens=2):
    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(
            empresa_id=empresa_id, emissor="Nubank", final_numero="1234",
            titular="Camilo", conta_codigo=CONTA_CARTAO,
        )
        uow.cartoes_credito.salvar_se_novo(cartao)

        valor_item = Decimal(valor_total) / n_itens
        fatura = FaturaCartao(
            empresa_id=empresa_id, cartao_id=cartao.id,
            periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
            valor_total_declarado=Dinheiro(Decimal(valor_total)),
        )
        for _ in range(n_itens):
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(valor_item), posicao_linha=len(fatura.itens) + 1,
            ))
        fatura.validar_fechamento()
        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()

    return fatura.id


# =============================================================
# POSITIVO
# =============================================================

class TestLocalizacaoPositiva:
    def test_localiza_pagamento_apos_b6_0(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id = _fatura_fechada_persistida(sf, empresa_id)

        GerarLancamentosFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        resultado = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf).executar(fatura_id)

        assert resultado.fatura_id == fatura_id
        assert resultado.lancamento_pagamento is not None
        assert resultado.lancamento_pagamento.valor_total.valor == Decimal("150.00")

    def test_id_retornado_bate_com_a_formula_deterministica(self):
        """Prova que o resultado é exatamente calcular_id_lancamento_pagamento(fatura_id),
        não um id descoberto por outro caminho."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id = _fatura_fechada_persistida(sf, empresa_id)

        GerarLancamentosFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        resultado = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf).executar(fatura_id)

        assert resultado.lancamento_pagamento_id == calcular_id_lancamento_pagamento(fatura_id)


# =============================================================
# NEGATIVO
# =============================================================

class TestBloqueiosObrigatorios:
    def test_fatura_inexistente_levanta_erro(self):
        sf = _session_factory()
        uc = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(FaturaNaoEncontradaError):
            uc.executar(uuid4())

    def test_fatura_sem_b6_0_executado_levanta_erro(self):
        """Fatura existe e está FECHADA, mas B6-0 nunca rodou — não há
        lançamento de pagamento para localizar."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id = _fatura_fechada_persistida(sf, empresa_id)

        uc = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(PagamentoNaoGeradoError):
            uc.executar(fatura_id)


# =============================================================
# GUARDRAIL CENTRAL — nunca localizar por heurística
# =============================================================

class TestNuncaPorHeuristica:
    def test_lancamento_com_mesmo_valor_e_data_mas_id_diferente_nao_e_encontrado(self):
        """Existe um Lancamento 'parecido' com o pagamento esperado
        (mesmo valor, mesma data, categoria vazia como D8) — mas com id
        aleatório, não o determinístico. B6-1 deve IGNORÁ-LO e levantar
        PagamentoNaoGeradoError, nunca 'confundir' por coincidência de
        valor/data/categoria — essa é a garantia central do guardrail."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00")

        # Lançamento "impostor": mesmo valor, mesma data de vencimento,
        # categoria None (como D8 real) — mas id aleatório, não o
        # determinístico esperado para esta fatura.
        impostor = Lancamento(
            empresa_id=empresa_id,
            data_lancamento=date(2026, 9, 15),
            descricao="Pagamento fatura cartão — período 2026-08-01",
            status=StatusLancamento.APROVADO,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
            splits=[
                Split(conta=CONTA_CARTAO, natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal("150.00"))),
                Split(conta=CONTA_BANCO, natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal("150.00"))),
            ],
        )
        with UnitOfWork(sf) as uow:
            uow.lancamentos.salvar(impostor)
            uow.commit()

        uc = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(PagamentoNaoGeradoError):
            uc.executar(fatura_id)  # não encontra o impostor por acaso

    def test_apos_b6_0_real_localiza_o_correto_nao_o_impostor(self):
        """Com o impostor presente E o pagamento real gerado por B6-0,
        B6-1 deve retornar exatamente o real (id determinístico),
        nunca o impostor — mesmo ambos tendo valor/data idênticos."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00")

        impostor = Lancamento(
            empresa_id=empresa_id,
            data_lancamento=date(2026, 9, 15),
            descricao="Pagamento fatura cartão — período 2026-08-01",
            status=StatusLancamento.APROVADO,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
            splits=[
                Split(conta=CONTA_CARTAO, natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal("150.00"))),
                Split(conta=CONTA_BANCO, natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal("150.00"))),
            ],
        )
        with UnitOfWork(sf) as uow:
            uow.lancamentos.salvar(impostor)
            uow.commit()

        GerarLancamentosFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        resultado = LocalizarPagamentoFaturaCartaoUseCase(session_factory=sf).executar(fatura_id)

        assert resultado.lancamento_pagamento_id != impostor.id
        assert resultado.lancamento_pagamento_id == calcular_id_lancamento_pagamento(fatura_id)
