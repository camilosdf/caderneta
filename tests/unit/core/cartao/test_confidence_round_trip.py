"""Testes de DT-CC-02 (ADR 010) — persistência de CompraCartao.confidence.

Antes desta correção, CompraCartaoORM não tinha colunas para
ConfidenceScore e _item_para_dominio hardcodeava confidence=None —
qualquer score atribuído na Fase 2 (extração/classificação) era
descartado ao persistir e reler uma fatura. LancamentoService já
propagava corretamente compra.confidence para Lancamento.confidence
(D7) — o elo quebrado era só a persistência, não B6-0 em si.

TestRoundTripConfidence cobre o repositório isoladamente. Test
ConfidencePreservadaEmB60 cobre a regressão ponta a ponta: fatura
persistida e recarregada (não o mesmo objeto Python) -> lançamento
gerado por GerarLancamentosFaturaCartaoUseCase reflete o confidence
que estava salvo no banco, não um valor perdido no meio do caminho.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    GerarLancamentosFaturaCartaoUseCase,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    ConfidenceScore,
    Dinheiro,
    FaturaCartao,
    StatusFechamentoFatura,
    TipoItemFatura,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {
    TipoItemFatura.COMPRA: CodigoConta("4.1.01.001"),
}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


def _cartao_persistido(uow, empresa_id):
    cartao = CartaoCredito(
        empresa_id=empresa_id, emissor="Nubank", final_numero="1234",
        titular="Camilo", conta_codigo=CONTA_CARTAO,
    )
    uow.cartoes_credito.salvar_se_novo(cartao)
    return cartao


# =============================================================
# Round-trip isolado no repositório
# =============================================================

class TestRoundTripConfidence:
    def test_confidence_sobrevive_ao_round_trip(self):
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = _cartao_persistido(uow, empresa_id)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("100.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("100.00")), posicao_linha=1,
                confidence=ConfidenceScore(valor=0.87, campo="estabelecimento"),
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        # Sessão nova — sem cache de identidade do UnitOfWork anterior.
        with UnitOfWork(sf) as uow2:
            recarregada = uow2.faturas_cartao.buscar_por_id(fatura_id)

        assert recarregada is not None
        assert len(recarregada.itens) == 1
        item = recarregada.itens[0]
        assert item.confidence is not None
        assert item.confidence.valor == 0.87
        assert item.confidence.campo == "estabelecimento"

    def test_item_sem_confidence_permanece_none_apos_round_trip(self):
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = _cartao_persistido(uow, empresa_id)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("50.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("50.00")), posicao_linha=1,
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        with UnitOfWork(sf) as uow2:
            recarregada = uow2.faturas_cartao.buscar_por_id(fatura_id)

        assert recarregada.itens[0].confidence is None

    def test_multiplos_itens_com_confidences_diferentes_preservados_independentemente(self):
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = _cartao_persistido(uow, empresa_id)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("300.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("100.00")), posicao_linha=1,
                confidence=ConfidenceScore(valor=0.95, campo="valor"),
            ))
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("100.00")), posicao_linha=2,
                confidence=None,
            ))
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("100.00")), posicao_linha=3,
                confidence=ConfidenceScore(valor=0.42, campo="tipo"),
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        with UnitOfWork(sf) as uow2:
            recarregada = uow2.faturas_cartao.buscar_por_id(fatura_id)

        por_posicao = {i.posicao_linha: i for i in recarregada.itens}
        assert por_posicao[1].confidence.valor == 0.95
        assert por_posicao[1].confidence.campo == "valor"
        assert por_posicao[2].confidence is None
        assert por_posicao[3].confidence.valor == 0.42
        assert por_posicao[3].confidence.campo == "tipo"


# =============================================================
# Regressão B6-0 — confidence sobrevive persistência -> geração de lançamento
# =============================================================

class TestConfidencePreservadaEmB60:
    def test_confidence_baixa_chega_ao_lancamento_via_b60(self):
        """Reproduz o cenário real: fatura persistida e fechada em uma
        transação; GerarLancamentosFaturaCartaoUseCase abre sua própria
        UnitOfWork e recarrega do banco — não reaproveita o objeto Python
        original. Antes da correção, confidence virava None nesse ponto
        e Lancamento.confidence saía sempre None, mesmo com um score
        baixo (<0.90) que deveria acionar Lancamento.precisa_revisao.
        """
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = _cartao_persistido(uow, empresa_id)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("60.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("60.00")), posicao_linha=1,
                confidence=ConfidenceScore(valor=0.55, campo="estabelecimento"),
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        with UnitOfWork(sf) as uow3:
            lancamento_compra = uow3.lancamentos.buscar_por_id(
                resultado.lancamentos_compra_ids[0]
            )

        assert lancamento_compra.confidence == 0.55
        assert lancamento_compra.precisa_revisao is True

    def test_sem_confidence_lancamento_gerado_normalmente_sem_erro(self):
        """Item sem confidence (fluxo majoritário hoje) não deve quebrar
        nem inventar um score — Lancamento.confidence permanece None."""
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = _cartao_persistido(uow, empresa_id)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("40.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("40.00")), posicao_linha=1,
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        with UnitOfWork(sf) as uow3:
            lancamento_compra = uow3.lancamentos.buscar_por_id(
                resultado.lancamentos_compra_ids[0]
            )

        assert lancamento_compra.confidence is None
