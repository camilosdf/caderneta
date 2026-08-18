"""Testes de CLI — `cartao importar` e `cartao listar` (ADR 010, Fase 4).

Usa typer.testing.CliRunner (execução in-process). pdfplumber.open é
mockado — mesmo padrão hermético das demais suítes de cartão. Cada
teste usa --datalake apontando para tmp_path, garantindo banco SQLite
isolado por teste.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from core.cli import app

runner = CliRunner()

_TEXTO_FATURA_FECHADA = """\
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
06/08 IFOOD DELIVERY R$ 48,50
Total desta fatura R$ 74,40
"""


@pytest.fixture(autouse=True)
def _forcar_sqlite_via_datalake(monkeypatch):
    """tests/conftest.py define uma URL de banco externo (esquema
    Postgres) como autouse global, para os testes de api/. Os comandos
    de CLI aqui testados usam --datalake para apontar SQLite isolado
    por teste — sem remover essa URL, _session_factory() (core/cli.py)
    priorizaria o banco externo, inexistente neste ambiente de teste."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _pdfplumber_mock(texto: str):
    pagina = MagicMock()
    pagina.extract_text.return_value = texto
    pdf_mock = MagicMock()
    pdf_mock.__enter__.return_value.pages = [pagina]
    pdf_mock.__exit__.return_value = False
    return pdf_mock


@pytest.fixture
def fatura_pdf(tmp_path: Path) -> Path:
    """Arquivo com extensão .pdf e conteúdo mínimo de assinatura PDF —
    suficiente para o detector reconhecer a extensão; o conteúdo real
    (texto extraído) vem do mock de pdfplumber.open, não deste arquivo."""
    f = tmp_path / "fatura.pdf"
    f.write_bytes(b"%PDF-1.4 fake pdf content for extension detection")
    return f


def _args_importar(fatura_pdf: Path, datalake: Path, empresa: str = "empresa-teste") -> list[str]:
    return [
        "cartao", "importar", str(fatura_pdf),
        "--empresa", empresa,
        "--emissor", "Nubank",
        "--final", "1234",
        "--titular", "Camilo",
        "--conta", "2.1.05.001",
        "--datalake", str(datalake),
    ]


class TestCartaoImportar:
    def test_importa_fatura_com_sucesso(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl1"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            resultado = runner.invoke(app, _args_importar(fatura_pdf, datalake))

        assert resultado.exit_code == 0
        assert "Fatura importada" in resultado.stdout
        assert "2" in resultado.stdout  # 2 itens

    def test_cartao_criado_na_primeira_importacao(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl2"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            resultado = runner.invoke(app, _args_importar(fatura_pdf, datalake))

        assert "novo" in resultado.stdout

    def test_reimportar_mesma_fatura_e_idempotente(self, fatura_pdf: Path, tmp_path: Path):
        """D13 via CLI — segunda importação do mesmo arquivo/cartão não duplica."""
        datalake = tmp_path / "dl3"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            runner.invoke(app, _args_importar(fatura_pdf, datalake))
            resultado2 = runner.invoke(app, _args_importar(fatura_pdf, datalake))

        assert resultado2.exit_code == 0
        assert "já processada" in resultado2.stdout.lower() or "já cadastrado" in resultado2.stdout.lower()

    def test_segunda_importacao_reaproveita_cartao_nao_cria_novo(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl4"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            runner.invoke(app, _args_importar(fatura_pdf, datalake))
            resultado2 = runner.invoke(app, _args_importar(fatura_pdf, datalake))

        assert "já cadastrado" in resultado2.stdout.lower()

    def test_arquivo_inexistente_falha_com_mensagem_clara(self, tmp_path: Path):
        datalake = tmp_path / "dl5"
        resultado = runner.invoke(
            app, _args_importar(tmp_path / "nao_existe.pdf", datalake)
        )
        assert resultado.exit_code == 1

    def test_pdf_sem_campos_de_fatura_falha_com_mensagem_clara(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl6"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock("texto qualquer sem fatura")):
            resultado = runner.invoke(app, _args_importar(fatura_pdf, datalake))

        assert resultado.exit_code == 1


class TestCartaoListar:
    def test_lista_vazia_quando_nao_ha_faturas(self, tmp_path: Path):
        datalake = tmp_path / "dl_vazio"
        resultado = runner.invoke(
            app, ["cartao", "listar", "--empresa", "empresa-teste", "--datalake", str(datalake)]
        )
        assert resultado.exit_code == 0
        assert "nenhuma fatura" in resultado.stdout.lower()

    def test_lista_fatura_apos_importacao(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl_listar"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            runner.invoke(app, _args_importar(fatura_pdf, datalake))

        resultado = runner.invoke(
            app, ["cartao", "listar", "--empresa", "empresa-teste", "--datalake", str(datalake)]
        )

        assert resultado.exit_code == 0
        assert "2026-08-01" in resultado.stdout
        assert "fechada" in resultado.stdout.lower()

    def test_lista_nao_mistura_empresas_diferentes(self, fatura_pdf: Path, tmp_path: Path):
        datalake = tmp_path / "dl_multi"
        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            runner.invoke(app, _args_importar(fatura_pdf, datalake, empresa="empresa-A"))

        resultado = runner.invoke(
            app, ["cartao", "listar", "--empresa", "empresa-B", "--datalake", str(datalake)]
        )
        assert "nenhuma fatura" in resultado.stdout.lower()
