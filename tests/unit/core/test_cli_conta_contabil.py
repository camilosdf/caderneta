"""Testes de CLI — `conta criar` e `conta listar` (DT-CC-01 / ADR 011, B.2.3).

Mesmo padrão hermético de tests/unit/core/cartao/test_cli_cartao.py:
typer.testing.CliRunner in-process, --datalake isolado por teste em
tmp_path.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from core.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _forcar_sqlite_via_datalake(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


class TestContaCriar:
    def test_criar_conta_com_sucesso(self, tmp_path: Path) -> None:
        resultado = runner.invoke(app, [
            "conta", "criar", "4.1.01.001", "Despesas Operacionais",
            "--empresa", "empresa-teste",
            "--datalake", str(tmp_path),
        ])
        assert resultado.exit_code == 0
        assert "Conta contábil criada" in resultado.stdout

    def test_criar_conta_codigo_duplicado_falha(self, tmp_path: Path) -> None:
        args = [
            "conta", "criar", "4.1.01.002", "Combustível",
            "--empresa", "empresa-teste",
            "--datalake", str(tmp_path),
        ]
        primeiro = runner.invoke(app, args)
        assert primeiro.exit_code == 0

        segundo = runner.invoke(app, ["conta", "criar", "4.1.01.002", "Duplicada",
                                       "--empresa", "empresa-teste", "--datalake", str(tmp_path)])
        assert segundo.exit_code == 1

    def test_criar_conta_natureza_invalida_falha(self, tmp_path: Path) -> None:
        resultado = runner.invoke(app, [
            "conta", "criar", "4.1.01.003", "Teste",
            "--empresa", "empresa-teste",
            "--natureza", "invalida",
            "--datalake", str(tmp_path),
        ])
        assert resultado.exit_code == 1
        assert "Natureza inválida" in resultado.stdout

    def test_criar_conta_nao_lancavel(self, tmp_path: Path) -> None:
        resultado = runner.invoke(app, [
            "conta", "criar", "4.1.01", "Sintética",
            "--empresa", "empresa-teste",
            "--nao-lancavel",
            "--datalake", str(tmp_path),
        ])
        assert resultado.exit_code == 0

        listagem = runner.invoke(app, [
            "conta", "listar", "--empresa", "empresa-teste", "--datalake", str(tmp_path),
        ])
        assert "não" in listagem.stdout  # coluna "Lançável"

    def test_mesmo_codigo_empresas_diferentes_permitido(self, tmp_path: Path) -> None:
        r1 = runner.invoke(app, ["conta", "criar", "4.1.01.004", "A",
                                  "--empresa", "empresa-x", "--datalake", str(tmp_path)])
        r2 = runner.invoke(app, ["conta", "criar", "4.1.01.004", "B",
                                  "--empresa", "empresa-y", "--datalake", str(tmp_path)])
        assert r1.exit_code == 0
        assert r2.exit_code == 0


class TestContaListar:
    def test_listar_sem_contas_cadastradas(self, tmp_path: Path) -> None:
        resultado = runner.invoke(app, [
            "conta", "listar", "--empresa", "empresa-vazia", "--datalake", str(tmp_path),
        ])
        assert resultado.exit_code == 0
        assert "Nenhuma conta contábil cadastrada" in resultado.stdout

    def test_listar_mostra_contas_criadas(self, tmp_path: Path) -> None:
        runner.invoke(app, ["conta", "criar", "4.1.01.005", "Alpha",
                             "--empresa", "empresa-teste", "--datalake", str(tmp_path)])
        runner.invoke(app, ["conta", "criar", "1.1.01.006", "Beta",
                             "--empresa", "empresa-teste", "--natureza", "credito",
                             "--datalake", str(tmp_path)])

        resultado = runner.invoke(app, [
            "conta", "listar", "--empresa", "empresa-teste", "--datalake", str(tmp_path),
        ])
        assert resultado.exit_code == 0
        assert "4.1.01.005" in resultado.stdout
        assert "Alpha" in resultado.stdout
        assert "1.1.01.006" in resultado.stdout
        assert "Beta" in resultado.stdout

    def test_listar_nao_mistura_empresas(self, tmp_path: Path) -> None:
        runner.invoke(app, ["conta", "criar", "4.1.01.007", "Só de X",
                             "--empresa", "empresa-x", "--datalake", str(tmp_path)])

        resultado = runner.invoke(app, [
            "conta", "listar", "--empresa", "empresa-y", "--datalake", str(tmp_path),
        ])
        assert "4.1.01.007" not in resultado.stdout
