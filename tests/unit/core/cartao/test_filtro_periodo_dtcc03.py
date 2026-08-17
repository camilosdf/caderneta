"""Teste de DT-CC-03 — filtro de período nativo em conciliacao_executar.

Antes desta correção, `conciliacao_executar` buscava até `limit=100`
lançamentos aprovados SEM filtro de data na query, filtrando por
período depois em Python — uma empresa com mais de 100 lançamentos
aprovados (independente do período) podia ter lançamentos relevantes
do período alvo cortados pelo limit antes do filtro de data.

Este teste cria mais de 100 lançamentos aprovados fora do período alvo
e 1 dentro dele — se o bug existisse, o lançamento relevante poderia
não ser considerado. Com a correção, o filtro acontece na query SQL,
então o único lançamento do período é encontrado independentemente de
quantos outros existam fora dele.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from core.cli import app
from core.domain.entities import (
    CodigoConta,
    ContaBancaria,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    TransacaoBancaria,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from shared.identifiers import empresa_id_from_string

runner = CliRunner()


@pytest.fixture(autouse=True)
def _forcar_sqlite_via_datalake(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _session_factory_arquivo(datalake: Path) -> SessionFactory:
    datalake.mkdir(parents=True, exist_ok=True)
    sf = SessionFactory(f"sqlite:///{datalake / 'caderneta.db'}")
    sf.criar_tabelas()
    return sf


def _lancamento(empresa_id, data_lanc, valor="10.00", descricao="teste"):
    return Lancamento(
        empresa_id=empresa_id, data_lancamento=data_lanc, descricao=descricao,
        status=StatusLancamento.APROVADO, nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        splits=[
            Split(conta=CodigoConta("4.1.01.999"), natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.999"), natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal(valor))),
        ],
    )


class TestFiltroPeriodoNativoDTCC03:
    def test_filtro_nativo_encontra_lancamento_do_periodo_com_limit_restritivo(self, tmp_path):
        datalake = tmp_path / "dl_dtcc03"
        sf = _session_factory_arquivo(datalake)
        empresa_str = "empresa-dtcc03"
        empresa_id = empresa_id_from_string(empresa_str)
        with UnitOfWork(sf) as uow:
            for i in range(150):
                uow.lancamentos.salvar(_lancamento(empresa_id, date(2026, 1, 1), descricao=f"fora-{i}"))
            lanc_alvo = _lancamento(empresa_id, date(2026, 9, 15), valor="500.00", descricao="dentro-do-periodo")
            uow.lancamentos.salvar(lanc_alvo)
            uow.commit()
            id_lancamento_alvo = lanc_alvo.id
        with UnitOfWork(sf) as uow:
            resultado = uow.lancamentos.listar_por_empresa(
                empresa_id, status=StatusLancamento.APROVADO,
                data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30),
                limit=1,
            )
        assert len(resultado) == 1
        assert resultado[0].id == id_lancamento_alvo

    def test_conciliacao_executar_encontra_e_concilia_o_lancamento_do_periodo(self, tmp_path):
        """Prova de wiring real via CLI (limit padrão=100, não forçado).

        Os 150 lançamentos de ruído são datados DEPOIS do alvo (não
        antes) — é essa ordenação que reproduz o bug de fato: a query
        de LancamentoRepository.listar_por_empresa faz
        ORDER BY data_lancamento DESC antes do LIMIT. Com ruído mais
        antigo que o alvo (como numa primeira versão deste teste), o
        alvo — sendo o mais recente — sempre aparece nos top-100
        independentemente do filtro de data estar ou não na query,
        mascarando o bug (teste passa com ou sem a correção). Com
        ruído mais recente que o alvo, o alvo fica fora dos top-100
        sem o filtro nativo — reproduz o truncamento antes da correção
        e falha de forma determinística sem ela.
        """
        datalake = tmp_path / "dl_dtcc03_cli"
        sf = _session_factory_arquivo(datalake)
        empresa_str = "empresa-dtcc03-cli"
        empresa_id = empresa_id_from_string(empresa_str)
        with UnitOfWork(sf) as uow:
            lanc_alvo = _lancamento(empresa_id, date(2026, 9, 15), valor="500.00", descricao="dentro-do-periodo")
            uow.lancamentos.salvar(lanc_alvo)
            for i in range(150):
                uow.lancamentos.salvar(_lancamento(empresa_id, date(2026, 12, 1), descricao=f"fora-mais-recente-{i}"))
            uow.commit()
            id_lancamento_alvo = lanc_alvo.id
        tx = TransacaoBancaria(
            empresa_id=empresa_id,
            conta_bancaria=ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6"),
            fitid="TX-DTCC03-CLI", data=date(2026, 9, 15), valor=Dinheiro(Decimal("500.00")),
            natureza=NaturezaLancamento.DEBITO, descricao="TESTE",
        )
        with UnitOfWork(sf) as uow:
            uow.transacoes_bancarias.salvar_se_nova(tx)
            uow.commit()
        resultado = runner.invoke(app, [
            "conciliacao", "executar",
            "--empresa", empresa_str,
            "--periodo", "2026-09",
            "--datalake", str(datalake),
        ])
        assert resultado.exit_code == 0
        # Prova sobre o que o comando de fato processou (não uma nova
        # consulta corretamente filtrada por fora, que sempre acharia
        # o lançamento no banco independente do que o CLI fez).
        # Saída normalizada (sem quebras de linha) porque o Rich pode
        # quebrar a frase dependendo da largura do console no ambiente
        # de teste — a quebra em si não é o que este teste verifica.
        saida_normalizada = " ".join(resultado.stdout.split())
        assert "Lançamentos aprovados: 1" in saida_normalizada
        assert "Conciliação automática: 100.0%" in saida_normalizada
        with UnitOfWork(sf) as uow:
            lancamentos_filtrados = uow.lancamentos.listar_por_empresa(
                empresa_id, status=StatusLancamento.APROVADO,
                data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30),
            )
        ids_encontrados = {lanc.id for lanc in lancamentos_filtrados}
        assert id_lancamento_alvo in ids_encontrados
        assert len(lancamentos_filtrados) == 1

    def test_filtro_nativo_nao_quebra_lancamentos_sem_data(self, tmp_path):
        datalake = tmp_path / "dl_dtcc03_sem_data"
        sf = _session_factory_arquivo(datalake)
        empresa_id = empresa_id_from_string("empresa-dtcc03-sem-data")
        with UnitOfWork(sf) as uow:
            lanc_sem_data = _lancamento(empresa_id, None, descricao="sem-data")
            uow.lancamentos.salvar(lanc_sem_data)
            uow.commit()
        with UnitOfWork(sf) as uow:
            lancamentos_filtrados = uow.lancamentos.listar_por_empresa(
                empresa_id, status=StatusLancamento.APROVADO,
                data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30),
            )
        assert lancamentos_filtrados == []
