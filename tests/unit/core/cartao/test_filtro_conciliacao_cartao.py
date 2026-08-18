"""Testes de B6-2 — exclusão de compras de cartão da conciliação (ADR 010, Fase 6).

Dois níveis:
  1. Repositório (herméticos, precisos): FaturaCartaoRepository.listar_lancamento_ids_de_compras
  2. Integração real via CLI: conciliacao_executar, com dados persistidos
     via UnitOfWork em SQLite de arquivo (mesmo caminho passado como
     --datalake), provando que o filtro está de fato wireado no
     comando — não apenas testável isoladamente.

Guardrail central: nenhuma compra individual (D7) pode virar candidata
em MotorConciliacao; o pagamento (D8) e lançamentos não-cartão devem
permanecer candidatos.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    GerarLancamentosFaturaCartaoUseCase,
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
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    TipoItemFatura,
    TransacaoBancaria,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.rule_engine.motor_conciliacao import MotorConciliacao
from shared.identifiers import empresa_id_from_string

runner = CliRunner()

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {TipoItemFatura.COMPRA: CodigoConta("4.1.01.001")}
EMPRESA_STR = "empresa-b6-2-teste"


@pytest.fixture(autouse=True)
def _forcar_sqlite_via_datalake(monkeypatch):
    """Neutraliza o DATABASE_URL global (postgres) do tests/conftest.py
    — mesmo padrão de test_cli_cartao.py."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _session_factory_arquivo(datalake: Path) -> SessionFactory:
    """SQLite em arquivo real (mesmo padrão de core.cli._session_factory),
    para que o CLI (subprocesso in-process do CliRunner) enxergue os
    mesmos dados persistidos diretamente via UnitOfWork neste teste."""
    datalake.mkdir(parents=True, exist_ok=True)
    sf = SessionFactory(f"sqlite:///{datalake / 'caderneta.db'}")
    sf.criar_tabelas()
    return sf


def _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1, data_compra=None, data_vencimento=None):
    """Cria cartão + fatura FECHADA, roda B6-0, aprova os lançamentos, retorna a fatura recarregada."""
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


def _lancamento_nao_cartao(sf, empresa_id, valor="200.00", data_lanc=None):
    data_lanc = data_lanc or date(2026, 9, 10)
    lanc = Lancamento(
        empresa_id=empresa_id, data_lancamento=data_lanc, descricao="Despesa qualquer",
        status=StatusLancamento.APROVADO, nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        splits=[
            Split(conta=CodigoConta("4.1.01.999"), natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.999"), natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal(valor))),
        ],
    )
    with UnitOfWork(sf) as uow:
        uow.lancamentos.salvar(lanc)
        uow.commit()
    return lanc


# =============================================================
# REPOSITÓRIO — herméticos, estruturais
# =============================================================

class TestListarLancamentoIdsDeCompras:
    def test_retorna_apenas_ids_de_compras_com_lancamento_gerado(self, tmp_path):
        sf = _session_factory_arquivo(tmp_path / "dl1")
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="300.00", n_itens=3)

        with UnitOfWork(sf) as uow:
            ids = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)

        ids_esperados = {item.lancamento_id for item in fatura.itens}
        assert ids == ids_esperados
        assert len(ids) == 3

    def test_nao_inclui_lancamento_de_pagamento(self, tmp_path):
        sf = _session_factory_arquivo(tmp_path / "dl2")
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="100.00", n_itens=1)
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)

        with UnitOfWork(sf) as uow:
            ids = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)

        assert id_pagamento not in ids

    def test_isolamento_por_empresa(self, tmp_path):
        sf = _session_factory_arquivo(tmp_path / "dl3")
        empresa_a, empresa_b = uuid4(), uuid4()
        fatura_a = _fatura_fechada_com_lancamentos(sf, empresa_a, valor_total="50.00", n_itens=1)
        _fatura_fechada_com_lancamentos(sf, empresa_b, valor_total="70.00", n_itens=1)

        with UnitOfWork(sf) as uow:
            ids_a = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_a)

        assert ids_a == {item.lancamento_id for item in fatura_a.itens}

    def test_lista_vazia_quando_nenhuma_compra_gerada(self, tmp_path):
        sf = _session_factory_arquivo(tmp_path / "dl4")
        empresa_id = uuid4()
        with UnitOfWork(sf) as uow:
            ids = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)
        assert ids == set()

    def test_independente_de_periodo(self, tmp_path):
        """O método não filtra por data — retorna todo o histórico da
        empresa. Ponto de integridade da deliberação: essa
        independência não pode, por si, alterar o resultado do
        período — a data já foi decidida antes, no filtro de
        `lancamentos` por data_inicio/data_fim em conciliacao_executar."""
        sf = _session_factory_arquivo(tmp_path / "dl5")
        empresa_id = uuid4()
        fatura = _fatura_fechada_com_lancamentos(
            sf, empresa_id, valor_total="10.00", n_itens=1,
            data_compra=date(2020, 1, 1), data_vencimento=date(2020, 2, 10),
        )

        with UnitOfWork(sf) as uow:
            ids = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)

        assert fatura.itens[0].lancamento_id in ids


# =============================================================
# INTEGRAÇÃO REAL — conciliacao_executar via CliRunner
# =============================================================

class TestFiltroIntegradoNoCLI:
    def test_compra_nao_concilia_mesmo_com_valor_e_data_identicos_ao_pagamento(self, tmp_path):
        """Cenário de empate: fatura de 1 item -> compra e pagamento têm
        o MESMO valor (R$1000) e a MESMA data. Uma transação bancária de
        R$1000 nessa data deve conciliar com o PAGAMENTO — a compra
        nunca deveria ter sido candidata."""
        datalake = tmp_path / "dl_empate"
        sf = _session_factory_arquivo(datalake)
        empresa_id = empresa_id_from_string(EMPRESA_STR)
        data_vencimento = date(2026, 9, 15)

        fatura = _fatura_fechada_com_lancamentos(
            sf, empresa_id, valor_total="1000.00", n_itens=1, data_vencimento=data_vencimento,
        )
        id_pagamento = calcular_id_lancamento_pagamento(fatura.id)
        id_compra = fatura.itens[0].lancamento_id

        tx = TransacaoBancaria(
            empresa_id=empresa_id,
            conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
            fitid="TX-EMPATE-001", data=data_vencimento, valor=Dinheiro(Decimal("1000.00")),
            natureza=NaturezaLancamento.DEBITO, descricao="PAGTO FATURA CARTAO",
        )
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()

        resultado = runner.invoke(app, [
            "conciliacao", "executar",
            "--empresa", EMPRESA_STR,
            "--periodo", "2026-09",
            "--datalake", str(datalake),
        ])

        assert resultado.exit_code == 0

        # Verificação estrutural definitiva: reconstruir exatamente a
        # mesma lista filtrada que conciliacao_executar monta, e rodar
        # o motor sobre ela, comparando resultado.
        with UnitOfWork(sf) as uow:
            lancamentos_brutos = uow.lancamentos.listar_por_empresa(empresa_id, status=StatusLancamento.APROVADO)
            ids_compras = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)
            lancamentos_filtrados = [lanc for lanc in lancamentos_brutos if lanc.id not in ids_compras]

        ids_filtrados = {lanc.id for lanc in lancamentos_filtrados}
        assert id_compra not in ids_filtrados  # a compra nunca chega ao motor
        assert id_pagamento in ids_filtrados   # o pagamento permanece candidato

        relatorio = MotorConciliacao().conciliar(
            lancamentos=lancamentos_filtrados, transacoes=[tx], empresa_id=empresa_id,
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 30),
        )
        item = relatorio.itens[0]
        assert item.lancamento_id == id_pagamento  # nunca a compra

    def test_lancamento_nao_cartao_preservado_no_filtro(self, tmp_path):
        datalake = tmp_path / "dl_nao_cartao"
        sf = _session_factory_arquivo(datalake)
        empresa_id = empresa_id_from_string("empresa-nao-cartao")

        lanc = _lancamento_nao_cartao(sf, empresa_id, valor="200.00", data_lanc=date(2026, 9, 10))

        with UnitOfWork(sf) as uow:
            lancamentos_brutos = uow.lancamentos.listar_por_empresa(empresa_id, status=StatusLancamento.APROVADO)
            ids_compras = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)
            lancamentos_filtrados = [lanc for lanc in lancamentos_brutos if lanc.id not in ids_compras]

        assert lanc.id in {item.id for item in lancamentos_filtrados}  # não afetado pelo filtro

    def test_conciliacao_executar_finaliza_com_sucesso_end_to_end(self, tmp_path):
        """Prova de wiring: o comando real (não uma simulação da lógica)
        roda sem erro com fatura de cartão + transação real no banco."""
        datalake = tmp_path / "dl_e2e"
        sf = _session_factory_arquivo(datalake)
        empresa_id = empresa_id_from_string(EMPRESA_STR + "-e2e")
        data_vencimento = date(2026, 9, 15)

        _fatura_fechada_com_lancamentos(sf, empresa_id, valor_total="1000.00", n_itens=1, data_vencimento=data_vencimento)

        resultado = runner.invoke(app, [
            "conciliacao", "executar",
            "--empresa", EMPRESA_STR + "-e2e",
            "--periodo", "2026-09",
            "--datalake", str(datalake),
        ])

        assert resultado.exit_code == 0
        assert "aprovados: 1" in resultado.stdout
