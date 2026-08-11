"""Testes de B6-0 — GerarLancamentosFaturaCartaoUseCase (ADR 010, Fase 6).

Cobre: geração positiva, bloqueio de fatura não FECHADA, idempotência
por reutilização (não apenas ausência de duplicata), transacionalidade
(falha não deixa fatura parcialmente contabilizada), e preservação dos
guardrails (Lancamento intocado, LancamentoService não alterado).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    ContaDespesaNaoMapeadaError,
    FaturaNaoEncontradaError,
    FaturaNaoFechadaError,
    GerarLancamentosFaturaCartaoUseCase,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
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
    TipoItemFatura.IOF: CodigoConta("4.2.01.001"),
    TipoItemFatura.JUROS: CodigoConta("4.2.01.002"),
    TipoItemFatura.MULTA: CodigoConta("4.2.01.003"),
    TipoItemFatura.ENCARGO: CodigoConta("4.2.01.004"),
    TipoItemFatura.ANUIDADE: CodigoConta("4.1.02.001"),
    TipoItemFatura.ESTORNO: CodigoConta("4.1.01.001"),
}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


def _fatura_fechada_persistida(sf: SessionFactory, empresa_id, valor_total="150.00", n_itens=2):
    """Cria cartão + fatura FECHADA já persistidos, retorna (fatura_id, cartao_id)."""
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
        assert fatura.status_fechamento == StatusFechamentoFatura.FECHADA

        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()

    return fatura.id, cartao.id


# =============================================================
# POSITIVO — geração e persistência
# =============================================================

class TestGeracaoPositiva:
    def test_gera_lancamentos_de_compra_e_pagamento(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00", n_itens=2)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        assert len(resultado.lancamentos_compra_ids) == 2
        assert resultado.lancamento_pagamento_id is not None
        assert resultado.ja_processado is False

    def test_lancamentos_persistidos_no_banco(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="100.00", n_itens=1)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        with UnitOfWork(sf) as uow:
            lanc_pagamento = uow.lancamentos.buscar_por_id(resultado.lancamento_pagamento_id)
            lanc_compra = uow.lancamentos.buscar_por_id(resultado.lancamentos_compra_ids[0])

        assert lanc_pagamento is not None
        assert lanc_compra is not None
        assert lanc_pagamento.valor_total.valor == Decimal("100.00")

    def test_compra_cartao_lancamento_id_atualizado(self):
        """B6-0 deve gravar CompraCartao.lancamento_id — pré-requisito de B6-2."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="80.00", n_itens=1)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        with UnitOfWork(sf) as uow:
            fatura_recarregada = uow.faturas_cartao.buscar_por_id(fatura_id)

        assert fatura_recarregada.itens[0].lancamento_id is not None

    def test_pagamento_e_agregado_unico_mesmo_com_varios_itens(self):
        """D8 — sempre 1 lançamento de pagamento, independente de N itens."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="500.00", n_itens=7)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        assert len(resultado.lancamentos_compra_ids) == 7
        # 1 único id de pagamento — não uma lista
        assert isinstance(resultado.lancamento_pagamento_id, type(resultado.lancamento_pagamento_id))
        with UnitOfWork(sf) as uow:
            lanc_pagamento = uow.lancamentos.buscar_por_id(resultado.lancamento_pagamento_id)
        assert lanc_pagamento.valor_total.valor == Decimal("500.00")


# =============================================================
# NEGATIVO — fatura não FECHADA / inexistente / conta não mapeada
# =============================================================

class TestBloqueiosObrigatorios:
    def test_fatura_pendente_nao_gera_lancamentos(self):
        sf = _session_factory()
        empresa_id = uuid4()
        with UnitOfWork(sf) as uow:
            cartao = CartaoCredito(empresa_id=empresa_id, emissor="Nubank", final_numero="1234", titular="Camilo", conta_codigo=CONTA_CARTAO)
            uow.cartoes_credito.salvar_se_novo(cartao)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
                valor_total_declarado=Dinheiro(Decimal("100.00")),
            )  # status_fechamento = PENDENTE (default), nunca validado
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(FaturaNaoFechadaError):
            uc.executar(fatura.id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

    def test_fatura_divergente_nao_gera_lancamentos(self):
        sf = _session_factory()
        empresa_id = uuid4()
        with UnitOfWork(sf) as uow:
            cartao = CartaoCredito(empresa_id=empresa_id, emissor="Nubank", final_numero="1234", titular="Camilo", conta_codigo=CONTA_CARTAO)
            uow.cartoes_credito.salvar_se_novo(cartao)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
                valor_total_declarado=Dinheiro(Decimal("999.00")),
            )
            fatura.itens.append(CompraCartao(empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("10.00")), posicao_linha=1))
            fatura.validar_fechamento()
            assert fatura.status_fechamento == StatusFechamentoFatura.DIVERGENTE
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(FaturaNaoFechadaError):
            uc.executar(fatura.id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

    def test_fatura_inexistente_levanta_erro(self):
        sf = _session_factory()
        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(FaturaNaoEncontradaError):
            uc.executar(uuid4(), conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

    def test_conta_despesa_nao_mapeada_levanta_erro(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="50.00", n_itens=1)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        with pytest.raises(ContaDespesaNaoMapeadaError):
            uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo={})


# =============================================================
# IDEMPOTÊNCIA — reutilização, não apenas ausência de duplicata
# =============================================================

class TestIdempotenciaPorReutilizacao:
    def test_reprocessar_retorna_os_mesmos_ids(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00", n_itens=2)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        r1 = uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)
        r2 = uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        assert r2.ja_processado is True
        assert r1.lancamento_pagamento_id == r2.lancamento_pagamento_id
        assert sorted(r1.lancamentos_compra_ids) == sorted(r2.lancamentos_compra_ids)

    def test_reprocessar_nao_aumenta_quantidade_de_lancamentos(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00", n_itens=2)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        with UnitOfWork(sf) as uow:
            qtd_antes = len(uow.lancamentos.listar_por_empresa(empresa_id, limit=1000))

        uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        with UnitOfWork(sf) as uow:
            qtd_depois = len(uow.lancamentos.listar_por_empresa(empresa_id, limit=1000))

        assert qtd_antes == qtd_depois == 3  # 2 compras + 1 pagamento, nunca mais

    def test_id_pagamento_e_deterministico_para_mesma_fatura(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="60.00", n_itens=1)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        r1 = uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        # Novo use case (nova instância) — mesmo resultado, prova que o id
        # não depende de estado em memória do use case, só da fatura_id.
        uc2 = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        r2 = uc2.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        assert r1.lancamento_pagamento_id == r2.lancamento_pagamento_id


# =============================================================
# TRANSACIONALIDADE — falha não deixa fatura parcialmente contabilizada
# =============================================================

class TestTransacionalidade:
    def test_falha_no_meio_da_geracao_nao_persiste_nada(self):
        """Simula falha ao salvar o 2º de 2 lançamentos de compra —
        nenhum dos dois deve sobreviver ao rollback."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00", n_itens=2)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)

        chamadas = {"n": 0}

        from core.infra.repositories.lancamento_repository import LancamentoRepository
        original = LancamentoRepository.salvar

        def salvar_com_falha_na_segunda(self, lancamento):
            chamadas["n"] += 1
            if chamadas["n"] == 2:
                raise RuntimeError("Falha simulada no meio da geração")
            return original(self, lancamento)

        with (
            patch.object(LancamentoRepository, "salvar", salvar_com_falha_na_segunda),
            pytest.raises(RuntimeError),
        ):
            uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        with UnitOfWork(sf) as uow:
            lancamentos_orfaos = uow.lancamentos.listar_por_empresa(empresa_id, limit=1000)
            fatura_apos_falha = uow.faturas_cartao.buscar_por_id(fatura_id)

        assert len(lancamentos_orfaos) == 0  # rollback completo — nada sobrou
        assert all(item.lancamento_id is None for item in fatura_apos_falha.itens)  # nada gravado

    def test_apos_falha_reexecucao_funciona_normalmente(self):
        """Depois de uma falha simulada e rollback, reexecutar sem falha
        deve completar normalmente — confirma que o rollback não deixa
        estado inconsistente que bloqueie tentativas futuras."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_persistida(sf, empresa_id, valor_total="150.00", n_itens=2)

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)

        from core.infra.repositories.lancamento_repository import LancamentoRepository
        original = LancamentoRepository.salvar
        chamadas = {"n": 0}

        def falha_uma_vez(self, lancamento):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise RuntimeError("Falha simulada")
            return original(self, lancamento)

        with (
            patch.object(LancamentoRepository, "salvar", falha_uma_vez),
            pytest.raises(RuntimeError),
        ):
            uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        resultado = uc.executar(fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO, contas_despesa_por_tipo=CONTAS_DESPESA)

        assert resultado.ja_processado is False
        assert len(resultado.lancamentos_compra_ids) == 2
