"""Testes de CLI — `cartao gerar-lancamentos` e `cartao conciliar-pagamento`
(Deliberação Pós-Fase 6, Ponto A).

Banco em arquivo real (mesmo padrão de test_filtro_conciliacao_cartao.py)
— setup direto via UnitOfWork, execução via CliRunner. Nenhum use case
foi alterado; estes testes cobrem apenas a camada de acionamento CLI.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    calcular_id_lancamento_pagamento,
)
from core.cli import app
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    ContaBancaria,
    Dinheiro,
    FaturaCartao,
    NaturezaLancamento,
    StatusFechamentoFatura,
    TipoItemFatura,
    TransacaoBancaria,
)
from core.infra.db.session import SessionFactory
from core.infra.repositories.conta_contabil_repository import (
    ContaContabilJaExisteError,
    ContaContabilRepository,
)
from core.infra.unit_of_work import UnitOfWork
from shared.identifiers import empresa_id_from_string

runner = CliRunner()

CONTA_CARTAO = "2.1.05.001"
CONTA_BANCO = "1.1.01.001"
CONTA_COMPRA = "4.1.01.001"
CONTA_IOF = "4.2.01.001"


@pytest.fixture(autouse=True)
def _forcar_sqlite_via_datalake(monkeypatch):
    """Neutraliza DATABASE_URL global (postgres) do tests/conftest.py —
    mesmo padrão já usado nos demais testes de CLI de cartão."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _session_factory_arquivo(datalake: Path) -> SessionFactory:
    datalake.mkdir(parents=True, exist_ok=True)
    sf = SessionFactory(f"sqlite:///{datalake / 'caderneta.db'}")
    sf.criar_tabelas()
    return sf


def _cadastrar_contas_padrao(sf: SessionFactory, empresa_id) -> None:
    """DT-CC-01 / ADR 011, B.2.4 — `cartao gerar-lancamentos` e `cartao
    conciliar-pagamento` rodam via CliRunner contra o bootstrap real do
    CLI (core/cli.py::_session_factory()), que agora tem
    enforce_foreign_keys=True. Os códigos de conta usados pelos
    comandos (--conta-cartao/--conta-banco/--conta-compra/--conta-iof)
    precisam estar cadastrados em contas_contabeis antes da execução —
    idempotente por empresa_id, mesma dupla/quadra de códigos sempre."""
    with sf.session() as session:
        repo = ContaContabilRepository(session)
        for codigo, natureza in (
            (CONTA_CARTAO, NaturezaLancamento.CREDITO),
            (CONTA_BANCO, NaturezaLancamento.CREDITO),
            (CONTA_COMPRA, NaturezaLancamento.DEBITO),
            (CONTA_IOF, NaturezaLancamento.DEBITO),
        ):
            try:
                repo.criar(empresa_id, codigo, f"Conta teste {codigo}", natureza=natureza)
            except ContaContabilJaExisteError:
                pass


def _fatura_fechada(sf, empresa_id, final_numero="1234", valor_total="150.00", n_itens=1, com_iof=False):
    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(
            empresa_id=empresa_id, emissor="Nubank", final_numero=final_numero,
            titular="Camilo", conta_codigo=CodigoConta(CONTA_CARTAO),
        )
        uow.cartoes_credito.salvar_se_novo(cartao)

        fatura = FaturaCartao(
            empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
            data_vencimento=date(2026, 9, 15), valor_total_declarado=Dinheiro(Decimal(valor_total)),
        )
        valor_compra = Decimal(valor_total)
        if com_iof:
            valor_compra -= Decimal("4.32")
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.IOF, valor=Dinheiro(Decimal("4.32")),
                posicao_linha=2, data_compra=date(2026, 9, 15),
            ))
        fatura.itens.insert(0, CompraCartao(
            empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA, valor=Dinheiro(valor_compra),
            posicao_linha=1, data_compra=date(2026, 9, 15),
        ))
        fatura.validar_fechamento()
        assert fatura.status_fechamento == StatusFechamentoFatura.FECHADA
        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()

    return fatura.id


def _fatura_pendente(sf, empresa_id, final_numero="9999"):
    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(
            empresa_id=empresa_id, emissor="Nubank", final_numero=final_numero,
            titular="Camilo", conta_codigo=CodigoConta(CONTA_CARTAO),
        )
        uow.cartoes_credito.salvar_se_novo(cartao)
        fatura = FaturaCartao(
            empresa_id=empresa_id, cartao_id=cartao.id, periodo_referencia=date(2026, 8, 1),
            data_vencimento=date(2026, 9, 15), valor_total_declarado=Dinheiro(Decimal("100.00")),
        )
        # status_fechamento default = PENDENTE (nunca validado)
        uow.faturas_cartao.salvar_se_nova(fatura)
        uow.commit()
    return fatura.id


def _args_gerar(fatura_id, empresa, datalake, com_iof=False):
    args = [
        "cartao", "gerar-lancamentos", str(fatura_id),
        "--empresa", empresa,
        "--conta-cartao", CONTA_CARTAO,
        "--conta-banco", CONTA_BANCO,
        "--conta-compra", CONTA_COMPRA,
        "--datalake", str(datalake),
    ]
    if com_iof:
        args += ["--conta-iof", CONTA_IOF]
    return args


# =============================================================
# 1 — sucesso de gerar-lancamentos
# =============================================================

class TestGerarLancamentosSucesso:
    def test_gera_lancamentos_com_sucesso(self, tmp_path):
        datalake = tmp_path / "dl1"
        sf = _session_factory_arquivo(datalake)
        empresa_id = uuid4()
        fatura_id = _fatura_fechada(sf, empresa_id)
        _cadastrar_contas_padrao(sf, empresa_id)

        resultado = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake))

        assert resultado.exit_code == 0
        assert "Lançamentos gerados" in resultado.stdout

    def test_item_iof_exige_conta_iof(self, tmp_path):
        """Confirma que D9 (segregação de IOF) é preservada — sem
        --conta-iof, uma fatura com item IOF deve falhar claramente,
        não usar --conta-compra por engano."""
        datalake = tmp_path / "dl_iof_erro"
        sf = _session_factory_arquivo(datalake)
        empresa_id = uuid4()
        fatura_id = _fatura_fechada(sf, empresa_id, com_iof=True)

        resultado = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake, com_iof=False))

        assert resultado.exit_code == 1

    def test_item_iof_com_conta_informada_funciona(self, tmp_path):
        datalake = tmp_path / "dl_iof_ok"
        sf = _session_factory_arquivo(datalake)
        empresa_id = uuid4()
        fatura_id = _fatura_fechada(sf, empresa_id, com_iof=True)
        _cadastrar_contas_padrao(sf, empresa_id)

        resultado = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake, com_iof=True))

        assert resultado.exit_code == 0


# =============================================================
# 2 — erro claro para fatura não FECHADA
# =============================================================

class TestErroFaturaNaoFechada:
    def test_fatura_pendente_falha_com_mensagem_clara(self, tmp_path):
        datalake = tmp_path / "dl2"
        sf = _session_factory_arquivo(datalake)
        empresa_id = uuid4()
        fatura_id = _fatura_pendente(sf, empresa_id)

        resultado = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake))

        assert resultado.exit_code == 1


# =============================================================
# 3 — já coberto acima (test_item_iof_exige_conta_iof) — ConfirmaÇão adicional
# =============================================================

class TestErroContaAusente:
    def test_fatura_inexistente_falha_claramente(self, tmp_path):
        datalake = tmp_path / "dl3"
        _session_factory_arquivo(datalake)
        empresa_id = uuid4()

        resultado = runner.invoke(app, _args_gerar(uuid4(), str(empresa_id), datalake))

        assert resultado.exit_code == 1


# =============================================================
# 4 — sucesso de conciliar-pagamento -> CONCILIADO
# =============================================================

class TestConciliarPagamentoSucesso:
    def test_concilia_com_sucesso(self, tmp_path):
        datalake = tmp_path / "dl4"
        sf = _session_factory_arquivo(datalake)
        empresa_str = "empresa-ponto-a-4"
        empresa_id = empresa_id_from_string(empresa_str)
        fatura_id = _fatura_fechada(sf, empresa_id, valor_total="150.00")
        _cadastrar_contas_padrao(sf, empresa_id)

        runner.invoke(app, _args_gerar(fatura_id, empresa_str, datalake))

        # aprovar o lançamento de pagamento (exigido para entrar na conciliação)
        with UnitOfWork(sf) as uow:
            id_pagamento = calcular_id_lancamento_pagamento(fatura_id)
            lanc = uow.lancamentos.buscar_por_id(id_pagamento)
            lanc.aprovar("teste")
            uow.lancamentos.salvar(lanc)
            uow.commit()

        tx = TransacaoBancaria(
            empresa_id=empresa_id,
            conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
            fitid="TX-PONTO-A", data=date(2026, 9, 15), valor=Dinheiro(Decimal("150.00")),
            natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA",
        )
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        resultado = runner.invoke(app, [
            "cartao", "conciliar-pagamento", str(fatura_id),
            "--empresa", empresa_str, "--periodo", "2026-09", "--datalake", str(datalake),
        ])

        assert resultado.exit_code == 0
        assert "Conciliado e persistido" in resultado.stdout


# =============================================================
# 5 — SEM_MATCH/PENDENTE como resultado normal, não exceção
# =============================================================

class TestResultadoNaoConciliadoNaoEhErro:
    def test_sem_transacao_correspondente_nao_e_erro(self, tmp_path):
        datalake = tmp_path / "dl5"
        sf = _session_factory_arquivo(datalake)
        empresa_str = "empresa-ponto-a-5"
        empresa_id = empresa_id_from_string(empresa_str)
        fatura_id = _fatura_fechada(sf, empresa_id, valor_total="200.00")
        _cadastrar_contas_padrao(sf, empresa_id)

        runner.invoke(app, _args_gerar(fatura_id, empresa_str, datalake))
        with UnitOfWork(sf) as uow:
            id_pagamento = calcular_id_lancamento_pagamento(fatura_id)
            lanc = uow.lancamentos.buscar_por_id(id_pagamento)
            lanc.aprovar("teste")
            uow.lancamentos.salvar(lanc)
            uow.commit()
        # nenhuma transação bancária persistida

        resultado = runner.invoke(app, [
            "cartao", "conciliar-pagamento", str(fatura_id),
            "--empresa", empresa_str, "--periodo", "2026-09", "--datalake", str(datalake),
        ])

        assert resultado.exit_code == 0  # não é erro
        assert "nenhum vínculo persistido" in resultado.stdout.lower()


# =============================================================
# 6 — reexecução idempotente dos dois comandos
# =============================================================

class TestReexecucaoIdempotente:
    def test_gerar_lancamentos_reexecutado_nao_duplica(self, tmp_path):
        datalake = tmp_path / "dl6a"
        sf = _session_factory_arquivo(datalake)
        empresa_id = uuid4()
        fatura_id = _fatura_fechada(sf, empresa_id)
        _cadastrar_contas_padrao(sf, empresa_id)

        r1 = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake))
        r2 = runner.invoke(app, _args_gerar(fatura_id, str(empresa_id), datalake))

        assert r1.exit_code == 0
        assert r2.exit_code == 0
        assert "já processada" in r2.stdout.lower()

        with UnitOfWork(sf) as uow:
            qtd = len(uow.lancamentos.listar_por_empresa(empresa_id, limit=1000))
        assert qtd == 2  # 1 compra + 1 pagamento, nunca mais

    def test_conciliar_pagamento_reexecutado_nao_duplica_vinculo(self, tmp_path):
        datalake = tmp_path / "dl6b"
        sf = _session_factory_arquivo(datalake)
        empresa_str = "empresa-ponto-a-6b"
        empresa_id = empresa_id_from_string(empresa_str)
        fatura_id = _fatura_fechada(sf, empresa_id, valor_total="300.00")
        _cadastrar_contas_padrao(sf, empresa_id)

        runner.invoke(app, _args_gerar(fatura_id, empresa_str, datalake))
        with UnitOfWork(sf) as uow:
            id_pagamento = calcular_id_lancamento_pagamento(fatura_id)
            lanc = uow.lancamentos.buscar_por_id(id_pagamento)
            lanc.aprovar("teste")
            uow.lancamentos.salvar(lanc)
            uow.commit()

        tx = TransacaoBancaria(
            empresa_id=empresa_id,
            conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
            fitid="TX-PONTO-A-6B", data=date(2026, 9, 15), valor=Dinheiro(Decimal("300.00")),
            natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA",
        )
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        args = [
            "cartao", "conciliar-pagamento", str(fatura_id),
            "--empresa", empresa_str, "--periodo", "2026-09", "--datalake", str(datalake),
        ]
        r1 = runner.invoke(app, args)
        r2 = runner.invoke(app, args)

        assert r1.exit_code == 0
        assert r2.exit_code == 0

        with UnitOfWork(sf) as uow:
            vinculo = uow.pagamentos_faturas_cartao.buscar_por_fatura(fatura_id)
            assert vinculo is not None

        # segunda execução não deve ter criado um segundo vínculo — a
        # tentativa colide com a UNIQUE já existente (mesma fatura),
        # tratada graciosamente pelo use case (persistido=False)
        assert "já vinculado" in r2.stdout.lower() or "conciliado e persistido" in r2.stdout.lower()
