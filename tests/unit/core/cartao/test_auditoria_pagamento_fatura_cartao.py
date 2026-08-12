"""Testes de B6-7 — Auditoria da conciliação de pagamento (ADR 010, Fase 6).

Cobre: registro de TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO na hash
chain somente quando persistido=True, ausência de registro quando não
persistido (conflito de UNIQUE ou status != CONCILIADO), payload
correto, e integridade da chain preservada.

Não cobre publicação em EventBusPort — isso é B6-8, ainda não
autorizado.
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
from core.audit.chain import TipoEvento
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


def _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-B67"):
    return TransacaoBancaria(
        empresa_id=empresa_id,
        conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
        fitid=fitid, data=data, valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
    )


# =============================================================
# POSITIVO — registro de auditoria quando persistido
# =============================================================

class TestAuditoriaRegistradaQuandoPersistido:
    def test_evento_registrado_na_hash_chain(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, id_pagamento = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "1111")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30), usuario="analista")

        assert resultado.persistido is True
        assert resultado.auditoria_registrada is True

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id), tipo=TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO)

        assert len(eventos) == 1
        evento = eventos[0]
        assert evento["tipo"] == TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO.value
        assert evento["usuario"] == "analista"
        assert evento["payload"]["fatura_id"] == str(fatura_id)
        assert evento["payload"]["lancamento_id"] == str(id_pagamento)
        assert evento["payload"]["transacao_bancaria_id"] == str(tx.id)
        assert evento["payload"]["status"] == "conciliado"

    def test_usuario_padrao_sistema_quando_nao_informado(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "2222")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30)
        )

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id), tipo=TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO)

        assert eventos[0]["usuario"] == "sistema"

    def test_integridade_da_chain_preservada(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "3333")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30)
        )

        with UnitOfWork(sf) as uow:
            integra, erros = uow.audit.verificar_integridade()

        assert integra is True
        assert erros == []


# =============================================================
# NEGATIVO — sem persistência, sem auditoria
# =============================================================

class TestSemAuditoriaQuandoNaoPersistido:
    def test_sem_transacao_correspondente_nao_registra_auditoria(self):
        """status != CONCILIADO -> nem persiste, nem audita."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "4444")

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.persistido is False
        assert resultado.auditoria_registrada is False

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id), tipo=TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO)
        assert eventos == []

    def test_conflito_de_unicidade_nao_registra_auditoria_duplicada(self):
        """Duas faturas disputando a mesma transação -> só a que
        persistiu gera auditoria; a que perdeu não gera evento algum
        (não é um fato consumado)."""
        sf = _session_factory()
        empresa_id = uuid4()
        data_vencimento = date(2026, 9, 15)
        fatura_id_1, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "5555", "1000.00", data_vencimento)
        fatura_id_2, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "6666", "1000.00", data_vencimento)
        tx = _transacao(empresa_id, valor="1000.00", data=data_vencimento, fitid="TX-DISPUTA-B67")
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)
        r1 = uc.executar(fatura_id_1, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))
        r2 = uc.executar(fatura_id_2, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert r1.persistido != r2.persistido
        assert r1.auditoria_registrada == r1.persistido
        assert r2.auditoria_registrada == r2.persistido

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id), tipo=TipoEvento.PAGAMENTO_CARTAO_IDENTIFICADO)

        assert len(eventos) == 1  # exatamente um evento, nunca dois


# =============================================================
# NOTA: a classe TestB68NaoAntecipado (guardrail de B6-7, provando que
# EventBusPort ainda não era usado) foi removida nesta etapa — B6-8 foi
# autorizado e implementado (ver tests/unit/core/cartao/
# test_evento_pagamento_cartao_identificado.py para a cobertura atual
# de EventBusPort). Manter aquele teste aqui bloquearia permanentemente
# qualquer implementação válida de B6-8, o que não é seu propósito —
# ele existia para impedir ANTECIPAÇÃO indevida, não para proibir a
# funcionalidade após autorização explícita.
# =============================================================
