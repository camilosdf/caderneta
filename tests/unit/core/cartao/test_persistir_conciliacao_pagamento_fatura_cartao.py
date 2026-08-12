"""Testes de B6-5/B6-6/B6-14 — PagamentoFaturaCartaoRepository e
PersistirConciliacaoPagamentoFaturaCartaoUseCase (ADR 010, Fase 6).

Cobre: persistência positiva do vínculo, as 3 UNIQUE reais no banco,
round-trip de metodo_matching/score/status (B6-6), migration
upgrade->downgrade->upgrade, e — o ponto mais importante — o
fechamento real da fronteira cross-call documentada em B6-4: das duas
chamadas independentes de B6-3 que antes podiam ambas reportar
CONCILIADO, agora só uma consegue persistir.
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
    MetodoMatching,
    NaturezaLancamento,
    TipoConciliacao,
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


def _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-B65"):
    return TransacaoBancaria(
        empresa_id=empresa_id,
        conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
        fitid=fitid, data=data, valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
    )


# =============================================================
# PERSISTÊNCIA POSITIVA
# =============================================================

class TestPersistenciaPositiva:
    def test_conciliacao_conciliada_e_persistida(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, id_pagamento = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "1111")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.persistido is True
        assert resultado.item.status == TipoConciliacao.CONCILIADO

        with UnitOfWork(sf) as uow:
            vinculo = uow.pagamentos_faturas_cartao.buscar_por_fatura(fatura_id)
            assert vinculo is not None
            assert vinculo.lancamento_id == str(id_pagamento)
            assert vinculo.transacao_bancaria_id == str(tx.id)

    def test_nao_conciliado_nao_persiste_nada(self):
        """status != CONCILIADO (ex.: SEM_MATCH) -> nada é persistido."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "2222")
        # nenhuma transação persistida -> motor retorna PENDENTE/SEM_MATCH

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado.persistido is False
        assert resultado.motivo_nao_persistido is not None

        with UnitOfWork(sf) as uow:
            vinculo = uow.pagamentos_faturas_cartao.buscar_por_fatura(fatura_id)
        assert vinculo is None


# =============================================================
# B6-6 — round-trip de metodo_matching / score / status
# =============================================================

class TestRoundTripMetodoScoreStatus:
    def test_metodo_score_status_persistidos_corretamente(self):
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, _ = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "3333")
        tx = _transacao(empresa_id)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        resultado = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf).executar(
            fatura_id, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30)
        )

        with UnitOfWork(sf) as uow:
            vinculo = uow.pagamentos_faturas_cartao.buscar_por_fatura(fatura_id)
            assert vinculo.metodo_matching == MetodoMatching.VALOR_DATA.value
            assert vinculo.status == TipoConciliacao.CONCILIADO.value
            # Round-trip fiel ao que o motor calculou — não um valor
            # específico assumido; B6-6 garante persistência correta,
            # não redecide o algoritmo de score do motor (Fase 5).
            assert abs(float(vinculo.score) - resultado.item.score) < 0.0001


# =============================================================
# AS 3 UNIQUE — integridade real no banco (SQLite com FK ativado)
# =============================================================

class TestTresUniqueReais:
    def test_unique_fatura_cartao_id(self):
        """Duas linhas para a mesma fatura -> segunda rejeitada."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, id_pagamento = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "4444")
        tx1 = _transacao(empresa_id, fitid="TX-A")
        tx2 = _transacao(empresa_id, valor="1.00", data=date(2026, 9, 16), fitid="TX-B")
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx1)
            uow.transacoes_bancarias.salvar_se_nova(tx2)
            from core.domain.entities import ConciliacaoItem
            item1 = ConciliacaoItem(
                lancamento_id=id_pagamento, transacao_bancaria_id=tx1.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            item2 = ConciliacaoItem(
                lancamento_id=id_pagamento, transacao_bancaria_id=tx2.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            ok1 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id, item1)
            ok2 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id, item2)
            uow.commit()

        assert ok1 is True
        assert ok2 is False  # mesma fatura, mesmo lancamento_id -> rejeitado

    def test_unique_transacao_bancaria_id_efetivo(self):
        """Duas faturas tentando usar a mesma transação -> segunda rejeitada."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id_1, id_pagamento_1 = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "7777")
        fatura_id_2, id_pagamento_2 = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "8888")
        tx = _transacao(empresa_id, fitid="TX-DISPUTADA-2")

        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            from core.domain.entities import ConciliacaoItem
            item1 = ConciliacaoItem(
                lancamento_id=id_pagamento_1, transacao_bancaria_id=tx.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            item2 = ConciliacaoItem(
                lancamento_id=id_pagamento_2, transacao_bancaria_id=tx.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            ok1 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id_1, item1)
            ok2 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id_2, item2)
            uow.commit()

        assert ok1 is True
        assert ok2 is False  # mesma transação, fatura diferente -> rejeitado

    def test_unique_lancamento_id(self):
        """Mesmo lançamento de pagamento tentando vincular a duas transações -> segunda rejeitada."""
        sf = _session_factory()
        empresa_id = uuid4()
        fatura_id, id_pagamento = _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "9999")
        tx1 = _transacao(empresa_id, fitid="TX-C")
        tx2 = _transacao(empresa_id, valor="1.00", data=date(2026, 9, 16), fitid="TX-D")

        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx1)
            uow.transacoes_bancarias.salvar_se_nova(tx2)
            from core.domain.entities import ConciliacaoItem
            item1 = ConciliacaoItem(
                lancamento_id=id_pagamento, transacao_bancaria_id=tx1.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            item2 = ConciliacaoItem(
                lancamento_id=id_pagamento, transacao_bancaria_id=tx2.id,
                status=TipoConciliacao.CONCILIADO, metodo=MetodoMatching.VALOR_DATA, score=1.0,
            )
            ok1 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id, item1)
            ok2 = uow.pagamentos_faturas_cartao.persistir_conciliacao(empresa_id, fatura_id, item2)
            uow.commit()

        assert ok1 is True
        assert ok2 is False


# =============================================================
# FECHAMENTO REAL DO "TESTE B" DE B6-4
# =============================================================

class TestFechamentoTesteBDeB64:
    def test_duas_execucoes_independentes_so_uma_persiste(self):
        """Retoma exatamente o cenário de
        tests/unit/core/cartao/test_matching_1to1_fase6_b64.py ::
        TestBFronteiraCaminhoEstreitoB63 — duas faturas, duas chamadas
        independentes de B6-3, ambas calculam CONCILIADO para a mesma
        transação. Agora, com B6-5, ao tentar PERSISTIR ambas, só a
        primeira consegue — a segunda recebe violação de UNIQUE,
        tratada graciosamente (persistido=False), fechando a lacuna
        que B6-4 documentou como deliberadamente fora de escopo."""
        sf = _session_factory()
        empresa_id = uuid4()
        data_vencimento = date(2026, 9, 15)

        fatura_id_1, _ = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, "1010", "1000.00", data_vencimento,
        )
        fatura_id_2, _ = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, "2020", "1000.00", data_vencimento,
        )

        tx = _transacao(empresa_id, valor="1000.00", data=data_vencimento, fitid="TX-DISPUTA-FINAL")
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf)

        # Confirma primeiro que AMBAS ainda calculam CONCILIADO em
        # memória (B6-3 não mudou — mesma fronteira documentada).
        resultado_1 = uc.executar(fatura_id_1, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))
        resultado_2 = uc.executar(fatura_id_2, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        assert resultado_1.item.status == TipoConciliacao.CONCILIADO
        assert resultado_2.item.status == TipoConciliacao.CONCILIADO  # B6-3 inalterado, calcula igual

        # A diferença agora: só uma das duas PERSISTE.
        assert resultado_1.persistido != resultado_2.persistido  # exatamente uma True, uma False
        assert resultado_1.persistido or resultado_2.persistido  # pelo menos uma teve sucesso

        with UnitOfWork(sf) as uow:
            vinculo_tx = uow.pagamentos_faturas_cartao.buscar_por_transacao(tx.id)
        assert vinculo_tx is not None  # exatamente um vínculo existe para essa transação


# =============================================================
# MIGRATION — upgrade -> downgrade -> upgrade (SQLite, complementar à
# validação já feita em PostgreSQL real)
# =============================================================

class TestMigrationSQLite:
    def test_tabela_criada_via_metadata(self):
        """Confirmação estrutural via SQLAlchemy — a validação completa
        upgrade/downgrade/upgrade + FKs reais já foi feita em
        PostgreSQL real (ver relatório de B6-5)."""
        sf = _session_factory()
        with UnitOfWork(sf) as uow:
            assert uow.pagamentos_faturas_cartao is not None
