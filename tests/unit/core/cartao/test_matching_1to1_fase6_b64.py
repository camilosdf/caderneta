"""Testes de B6-4 — Preservar matching 1:1 (ADR 010, Fase 6).

Exatamente 2 testes, conforme plano revisado e aprovado:

  Teste A — caminho genérico (conciliacao_executar): duas faturas de
  cartão concorrendo pela mesma transação, processadas juntas.
  Demonstra, com dados reais de cartão, que o contrato 1:1 já testado
  genericamente em TestUnicidade (Fase 5) se aplica sem alteração —
  não duplica aqueles testes, verifica a integração ainda não coberta.

  Teste B — caminho estreito (B6-3): duas chamadas independentes de
  ConciliarPagamentoFaturaCartaoUseCase, mesma transação. Documenta a
  fronteira deliberada: B6-3 é isolado por fatura, sem estado entre
  chamadas — a proteção cross-call pertence a B6-5/B6-6/B6-14
  (constraints UNIQUE em pagamentos_faturas_cartao), não a este nível.
  NÃO é um teste de falha — comportamento atual é documentado, não
  corrigido aqui.

Nenhum código de produção foi alterado para estes testes.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from core.application.use_cases.conciliar_pagamento_fatura_cartao import (
    ConciliarPagamentoFaturaCartaoUseCase,
)
from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    GerarLancamentosFaturaCartaoUseCase,
    calcular_id_lancamento_pagamento,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    ContaBancaria,
    Dinheiro,
    FaturaCartao,
    NaturezaLancamento,
    StatusLancamento,
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


def _fatura_fechada_com_pagamento_aprovado(
    sf, empresa_id, final_numero, valor_total="1000.00", data_vencimento=None,
):
    """Cria cartão + fatura FECHADA, roda B6-0, aprova o pagamento.
    Cada chamada usa um final_numero diferente -> cartões distintos,
    faturas distintas, ambas podendo competir pela mesma transação."""
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
        # aprova também a compra (não entra no matching, mas precisa de
        # status consistente para não quebrar consultas gerais)
        item_compra = uow.faturas_cartao.buscar_por_id(fatura.id).itens[0]
        lanc_compra = uow.lancamentos.buscar_por_id(item_compra.lancamento_id)
        lanc_compra.aprovar("teste")
        uow.lancamentos.salvar(lanc_compra)
        uow.commit()

    return fatura.id, id_pagamento


def _transacao(empresa_id, valor="1000.00", data=date(2026, 9, 15), fitid="TX-DISPUTA"):
    return TransacaoBancaria(
        empresa_id=empresa_id,
        conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
        fitid=fitid, data=data, valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
    )


# =============================================================
# TESTE A — caminho genérico: duas faturas, mesma transação, processadas juntas
# =============================================================

class TestACaminhoGenericoDuasFaturasMesmaTransacao:
    def test_apenas_um_pagamento_e_conciliado_quando_dois_competem_pela_mesma_transacao(self):
        """Duas faturas de cartão diferentes, ambas com pagamento de
        R$1000 na mesma data, e UMA única transação de R$1000 na mesma
        data. Reproduz, com dados reais de cartão, o mesmo cenário já
        provado genericamente em TestUnicidade::
        test_transacao_conciliada_com_no_maximo_um_lancamento (Fase 5)
        — aqui a novidade é a integração real (B6-0 + B6-2), não o
        comportamento do motor em si, que permanece intocado."""
        sf = _session_factory()
        empresa_id = uuid4()
        data_vencimento = date(2026, 9, 15)

        _, id_pagamento_1 = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, final_numero="1111", valor_total="1000.00", data_vencimento=data_vencimento,
        )
        _, id_pagamento_2 = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, final_numero="2222", valor_total="1000.00", data_vencimento=data_vencimento,
        )

        tx = _transacao(empresa_id, valor="1000.00", data=data_vencimento)
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        # Reconstrói exatamente o que conciliacao_executar monta:
        # lançamentos aprovados do período, com compras excluídas (B6-2).
        with UnitOfWork(sf) as uow:
            lancamentos_brutos = uow.lancamentos.listar_por_empresa(empresa_id, status=StatusLancamento.APROVADO)
            ids_compras = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)
            lancamentos_filtrados = [lanc for lanc in lancamentos_brutos if lanc.id not in ids_compras]

        ids_filtrados = {lanc.id for lanc in lancamentos_filtrados}
        assert id_pagamento_1 in ids_filtrados
        assert id_pagamento_2 in ids_filtrados  # ambos são candidatos legítimos

        relatorio = MotorConciliacao().conciliar(
            lancamentos=lancamentos_filtrados, transacoes=[tx], empresa_id=empresa_id,
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 30),
        )

        conciliados = [i for i in relatorio.itens if i.status == TipoConciliacao.CONCILIADO]
        # Contrato 1:1: no máximo um dos dois pagamentos é conciliado
        # com a única transação disponível — nunca os dois.
        assert len(conciliados) <= 1
        if conciliados:
            assert conciliados[0].lancamento_id in {id_pagamento_1, id_pagamento_2}

        # A transação nunca aparece conciliada mais de uma vez.
        itens_da_tx = [i for i in relatorio.itens if i.transacao_bancaria_id == tx.id and i.status == TipoConciliacao.CONCILIADO]
        assert len(itens_da_tx) <= 1

    def test_conciliacao_executar_roda_sem_erro_com_duas_faturas_competindo(self):
        """Prova de wiring real via CLI (não apenas simulação da lógica)."""
        import tempfile
        from pathlib import Path as _Path

        from typer.testing import CliRunner

        from core.cli import app
        from shared.identifiers import empresa_id_from_string

        with tempfile.TemporaryDirectory() as tmp:
            datalake = _Path(tmp) / "dl"
            datalake.mkdir(parents=True, exist_ok=True)
            sf = SessionFactory(f"sqlite:///{datalake / 'caderneta.db'}")
            sf.criar_tabelas()
            empresa_str = "empresa-b6-4-teste"
            empresa_id = empresa_id_from_string(empresa_str)
            data_vencimento = date(2026, 9, 15)

            _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "3333", "1000.00", data_vencimento)
            _fatura_fechada_com_pagamento_aprovado(sf, empresa_id, "4444", "1000.00", data_vencimento)

            tx = _transacao(empresa_id, "1000.00", data_vencimento, fitid="TX-CLI")
            with UnitOfWork(sf) as uow:
                uow.transacoes_bancarias.salvar_se_nova(tx)
                uow.commit()

            import os
            os.environ.pop("DATABASE_URL", None)

            runner = CliRunner()
            resultado = runner.invoke(app, [
                "conciliacao", "executar",
                "--empresa", empresa_str,
                "--periodo", "2026-09",
                "--datalake", str(datalake),
            ])

            assert resultado.exit_code == 0


# =============================================================
# TESTE B — caminho estreito B6-3: documenta a fronteira, não corrige
# =============================================================

class TestBFronteiraCaminhoEstreitoB63:
    def test_duas_chamadas_independentes_de_b6_3_nao_compartilham_estado(self):
        """DOCUMENTA COMPORTAMENTO ATUAL, NÃO É TESTE DE FALHA.

        O use case de B6-3 (ConciliarPagamentoFaturaCartaoUseCase) é
        deliberadamente isolado por fatura e não mantém estado de
        concorrência entre chamadas independentes. A garantia
        cross-call NÃO pertence a B6-3; será materializada
        posteriormente pela persistência e pelas restrições únicas de
        `pagamentos_faturas_cartao` (fatura_cartao_id, lancamento_id,
        transacao_bancaria_id), conforme B6-5/B6-6/B6-14.

        Este teste comprova que, hoje, duas execuções isoladas de B6-3
        para faturas diferentes, competindo pela mesma transação,
        PODEM produzir o mesmo resultado (ambas CONCILIADO com a
        mesma transacao_bancaria_id) — sem levantar exceção, sem
        comportamento de erro. Isso NÃO constitui violação de B6-4:
        a proteção persistente está fora do escopo desta etapa.

        Se este teste um dia começar a falhar porque alguém introduziu
        estado global/compartilhado em B6-3 para "resolver" isso, essa
        mudança deve ser tratada como violação do guardrail de B6-3
        ("não alterar B6-3 para facilitar B6-4"), não como correção.
        """
        sf = _session_factory()
        empresa_id = uuid4()
        data_vencimento = date(2026, 9, 15)

        fatura_id_1, _ = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, final_numero="5555", valor_total="1000.00", data_vencimento=data_vencimento,
        )
        fatura_id_2, _ = _fatura_fechada_com_pagamento_aprovado(
            sf, empresa_id, final_numero="6666", valor_total="1000.00", data_vencimento=data_vencimento,
        )

        tx = _transacao(empresa_id, valor="1000.00", data=data_vencimento, fitid="TX-DISPUTA-B63")
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        uc = ConciliarPagamentoFaturaCartaoUseCase(session_factory=sf)

        # Duas chamadas completamente independentes — sem exceção em
        # nenhuma delas, cada uma "cega" à existência da outra.
        resultado_1 = uc.executar(fatura_id_1, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))
        resultado_2 = uc.executar(fatura_id_2, data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30))

        # Comportamento atual documentado: ambas podem reportar
        # CONCILIADO com a MESMA transação — comportamento esperado e
        # aceito neste nível, não uma falha a corrigir aqui.
        assert resultado_1.item.status == TipoConciliacao.CONCILIADO
        assert resultado_2.item.status == TipoConciliacao.CONCILIADO
        assert resultado_1.item.transacao_bancaria_id == tx.id
        assert resultado_2.item.transacao_bancaria_id == tx.id
        # A materialização da unicidade real (impedir que as DUAS sejam
        # persistidas) é responsabilidade de B6-5/B6-6/B6-14 — fora do
        # escopo desta etapa, propositalmente não testada aqui.
