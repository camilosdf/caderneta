"""Testes do Exportador CSV — Etapa 3.

Cobre: ExportadorCSV, Conferencia, ResultadoExportacao.
Meta: elevar cobertura de core/adapters/csv_exporter.py de 0% para ≥ 85%.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.adapters.csv_exporter import ExportadorCSV, Conferencia
from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
)


# =============================================================
# HELPERS
# =============================================================

def _lancamento(
    valor: str = "100.00",
    conta_debito: str = "4.1.01.001",
    conta_credito: str = "1.1.01.002",
    descricao: str = "SUPERMERCADO TESTE",
    categoria: str = "Alimentação",
    confidence: float = 0.99,
) -> Lancamento:
    v = Dinheiro(Decimal(valor))
    l = Lancamento(
        data_lancamento=date(2026, 6, 1),
        descricao=descricao,
        categoria=categoria,
        confidence=confidence,
        status=StatusLancamento.APROVADO,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        splits=[
            Split(conta=CodigoConta(conta_debito), natureza=NaturezaLancamento.DEBITO, valor=v),
            Split(conta=CodigoConta(conta_credito), natureza=NaturezaLancamento.CREDITO, valor=v),
        ],
    )
    l.validar()
    return l


# =============================================================
# EXPORTADOR CSV
# =============================================================

class TestExportadorCSV:
    def test_gera_arquivo_csv(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        lancamentos = [_lancamento()]
        resultado = exportador.exportar(lancamentos, tmp_path)
        assert resultado.caminho.exists()
        assert resultado.caminho.suffix == ".csv"

    def test_nome_arquivo_tem_timestamp(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento()], tmp_path, prefixo="inter")
        assert resultado.caminho.name.startswith("inter_")

    def test_hash_csv_calculado(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento()], tmp_path)
        assert len(resultado.hash_sha256) == 64

    def test_hash_csv_deterministico_para_mesmo_conteudo(self, tmp_path: Path) -> None:
        """Dois exports do mesmo lançamento devem ter hashes diferentes
        (por causa do timestamp no nome), mas o conteúdo interno é o mesmo."""
        exportador = ExportadorCSV()
        r1 = exportador.exportar([_lancamento("100.00")], tmp_path / "a")
        r2 = exportador.exportar([_lancamento("100.00")], tmp_path / "b")
        # Conteúdo igual → hashes iguais
        assert r1.hash_sha256 == r2.hash_sha256

    def test_total_lancamentos_correto(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar(
            [_lancamento("50.00"), _lancamento("75.00"), _lancamento("25.00")],
            tmp_path,
        )
        assert resultado.total_lancamentos == 3

    def test_total_valor_correto(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar(
            [_lancamento("50.00"), _lancamento("75.00")],
            tmp_path,
        )
        assert resultado.total_valor == Decimal("125.00")

    def test_csv_contem_cabecalho_gnucash(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento()], tmp_path)
        conteudo = resultado.caminho.read_text(encoding="utf-8-sig")
        assert "Date" in conteudo
        assert "Description" in conteudo
        assert "Account" in conteudo

    def test_csv_contem_codigo_conta(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar(
            [_lancamento(conta_debito="4.1.01.001", conta_credito="1.1.01.002")],
            tmp_path,
        )
        conteudo = resultado.caminho.read_text(encoding="utf-8-sig")
        assert "4.1.01.001" in conteudo
        assert "1.1.01.002" in conteudo

    def test_falha_com_lancamento_sem_splits(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        lancamento_vazio = Lancamento(
            data_lancamento=date(2026, 6, 1),
            descricao="SEM SPLITS",
        )
        with pytest.raises(ValueError, match="Conferência"):
            exportador.exportar([lancamento_vazio], tmp_path)

    def test_lancamento_parcelado_tem_sufixo(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        l = _lancamento(descricao="AMAZON PRIME")
        l.e_parcelado = True
        l.parcela_atual = 1
        l.total_parcelas = 3
        resultado = exportador.exportar([l], tmp_path)
        conteudo = resultado.caminho.read_text(encoding="utf-8-sig")
        assert "1/3" in conteudo

    def test_pasta_saida_criada_automaticamente(self, tmp_path: Path) -> None:
        nova_pasta = tmp_path / "saida" / "junho"
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento()], nova_pasta)
        assert nova_pasta.exists()
        assert resultado.caminho.exists()


# =============================================================
# CONFERÊNCIA
# =============================================================

class TestConferencia:
    def test_conferencia_valida(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento("100.00")], tmp_path)
        assert resultado.conferencia.valido is True
        assert resultado.conferencia.erros == []

    def test_aviso_para_confianca_baixa(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar(
            [_lancamento(confidence=0.75)],
            tmp_path,
        )
        assert len(resultado.conferencia.avisos) > 0

    def test_sem_avisos_para_confianca_alta(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar(
            [_lancamento(confidence=0.99)],
            tmp_path,
        )
        assert len(resultado.conferencia.avisos) == 0

    def test_str_resultado_contem_status(self, tmp_path: Path) -> None:
        exportador = ExportadorCSV()
        resultado = exportador.exportar([_lancamento()], tmp_path)
        texto = str(resultado)
        assert "CSV gerado" in texto
        assert "Hash SHA-256" in texto
