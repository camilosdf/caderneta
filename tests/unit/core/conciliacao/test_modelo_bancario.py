"""Testes do modelo bancário — Etapa 8.1.

Cobre: TransacaoBancaria, ContaBancaria, chave de idempotência,
ConciliacaoItem, RelatorioConciliacao e BankStatementPort Protocol.
Herméticos: sem banco, sem arquivo, sem rede.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from core.domain.entities import (
    CandidatoMatch,
    ConciliacaoItem,
    ContaBancaria,
    Dinheiro,
    MetodoMatching,
    NaturezaLancamento,
    OrigemExtrato,
    RelatorioConciliacao,
    TipoConciliacao,
    TransacaoBancaria,
)
from core.ports.bank_statement import BankStatementPort


# =============================================================
# HELPERS
# =============================================================

def _conta(
    instituicao: str = "341",
    numero: str = "12345-6",
) -> ContaBancaria:
    return ContaBancaria(
        instituicao=instituicao,
        agencia="0001",
        numero_conta=numero,
        tipo_conta="corrente",
    )


def _tx(
    fitid: str = "TX001",
    valor: str = "100.00",
    natureza: NaturezaLancamento = NaturezaLancamento.DEBITO,
    descricao: str = "UBER DO BRASIL",
    data: date | None = None,
    conta: ContaBancaria | None = None,
) -> TransacaoBancaria:
    return TransacaoBancaria(
        empresa_id=uuid4(),
        conta_bancaria=conta or _conta(),
        fitid=fitid,
        data=data or date(2026, 7, 15),
        valor=Dinheiro(Decimal(valor)),
        natureza=natureza,
        descricao=descricao,
    )


def _item(status: TipoConciliacao) -> ConciliacaoItem:
    return ConciliacaoItem(
        lancamento_id=uuid4(),
        transacao_bancaria_id=uuid4(),
        status=status,
        metodo=MetodoMatching.VALOR_DATA,
        score=0.9,
    )


# =============================================================
# CONTA BANCÁRIA
# =============================================================

class TestContaBancaria:
    def test_str_inclui_instituicao_e_conta(self) -> None:
        conta = _conta(instituicao="341", numero="12345-6")
        assert "341" in str(conta)
        assert "12345-6" in str(conta)

    def test_igualdade_por_valor(self) -> None:
        c1 = ContaBancaria(instituicao="341", agencia="0001", numero_conta="123")
        c2 = ContaBancaria(instituicao="341", agencia="0001", numero_conta="123")
        assert c1 == c2

    def test_mesma_instituicao_contas_diferentes_nao_iguais(self) -> None:
        c1 = ContaBancaria(instituicao="341", numero_conta="111")
        c2 = ContaBancaria(instituicao="341", numero_conta="222")
        assert c1 != c2


# =============================================================
# TRANSAÇÃO BANCÁRIA — IDENTIDADE E IDEMPOTÊNCIA
# =============================================================

class TestTransacaoBancaria:
    def test_chave_idempotencia_inclui_instituicao_conta_fitid(self) -> None:
        tx = _tx(fitid="TX001")
        chave = tx.chave_idempotencia()
        assert "341" in chave
        assert "12345-6" in chave
        assert "TX001" in chave

    def test_mesmo_fitid_mesma_conta_mesma_chave(self) -> None:
        conta = _conta()
        tx1 = _tx(fitid="TX001", conta=conta)
        tx2 = _tx(fitid="TX001", conta=conta)
        assert tx1.chave_idempotencia() == tx2.chave_idempotencia()

    def test_mesmo_fitid_conta_diferente_chave_diferente(self) -> None:
        """FITID é único dentro de (instituição, conta), não globalmente."""
        conta_a = _conta(numero="111")
        conta_b = _conta(numero="222")
        tx1 = _tx(fitid="TX001", conta=conta_a)
        tx2 = _tx(fitid="TX001", conta=conta_b)
        assert tx1.chave_idempotencia() != tx2.chave_idempotencia()

    def test_fitid_diferente_chave_diferente(self) -> None:
        conta = _conta()
        tx1 = _tx(fitid="TX001", conta=conta)
        tx2 = _tx(fitid="TX002", conta=conta)
        assert tx1.chave_idempotencia() != tx2.chave_idempotencia()

    def test_valor_sempre_positivo(self) -> None:
        """Natureza indica direção; valor é sempre positivo (Dinheiro)."""
        tx = _tx(valor="250.00", natureza=NaturezaLancamento.DEBITO)
        assert tx.valor.valor == Decimal("250.00")

    def test_origem_padrao_ofx(self) -> None:
        tx = _tx()
        assert tx.origem == OrigemExtrato.OFX

    def test_ids_unicos_por_instancia(self) -> None:
        tx1 = _tx()
        tx2 = _tx()
        assert tx1.id != tx2.id


# =============================================================
# CANDIDATO MATCH
# =============================================================

class TestCandidatoMatch:
    def test_criacao_com_campos_minimos(self) -> None:
        c = CandidatoMatch(
            lancamento_id=uuid4(),
            metodo=MetodoMatching.FITID,
            score=1.0,
        )
        assert c.diferenca_valor == Decimal("0")
        assert c.diferenca_dias == 0
        assert c.evidencias == []

    def test_evidencias_podem_ser_registradas(self) -> None:
        c = CandidatoMatch(
            lancamento_id=uuid4(),
            metodo=MetodoMatching.VALOR_DATA,
            score=0.85,
            evidencias=["valor coincide", "data dentro da tolerância"],
        )
        assert len(c.evidencias) == 2


# =============================================================
# CONCILIAÇÃO ITEM — INVARIANTES
# =============================================================

class TestConciliacaoItem:
    def test_sem_lancamento_e_sem_transacao_e_valido(self) -> None:
        """SEM_DOCUMENTO: movimento bancário sem lançamento."""
        item = ConciliacaoItem(
            transacao_bancaria_id=uuid4(),
            lancamento_id=None,
            status=TipoConciliacao.SEM_DOCUMENTO,
        )
        assert item.lancamento_id is None

    def test_sem_transacao_e_valido(self) -> None:
        """PENDENTE: lançamento sem cobertura bancária."""
        item = ConciliacaoItem(
            lancamento_id=uuid4(),
            transacao_bancaria_id=None,
            status=TipoConciliacao.PENDENTE,
        )
        assert item.transacao_bancaria_id is None

    def test_candidatos_vazios_por_padrao(self) -> None:
        item = ConciliacaoItem()
        assert item.candidatos == []
        assert item.status == TipoConciliacao.PENDENTE

    def test_ids_unicos(self) -> None:
        i1 = ConciliacaoItem()
        i2 = ConciliacaoItem()
        assert i1.id != i2.id


# =============================================================
# RELATÓRIO DE CONCILIAÇÃO
# =============================================================

class TestRelatorioConciliacao:
    @pytest.fixture
    def relatorio(self) -> RelatorioConciliacao:
        r = RelatorioConciliacao(
            empresa_id=uuid4(),
            periodo_inicio=date(2026, 7, 1),
            periodo_fim=date(2026, 7, 31),
        )
        r.itens = [
            _item(TipoConciliacao.CONCILIADO),
            _item(TipoConciliacao.CONCILIADO),
            _item(TipoConciliacao.DIVERGENTE),
            _item(TipoConciliacao.AMBIGUO),
            _item(TipoConciliacao.PENDENTE),
            _item(TipoConciliacao.SEM_DOCUMENTO),
        ]
        return r

    def test_total_itens(self, relatorio) -> None:
        assert relatorio.total_itens == 6

    def test_conciliados(self, relatorio) -> None:
        assert len(relatorio.conciliados) == 2

    def test_divergentes(self, relatorio) -> None:
        assert len(relatorio.divergentes) == 1

    def test_ambiguos(self, relatorio) -> None:
        assert len(relatorio.ambiguos) == 1

    def test_pendentes(self, relatorio) -> None:
        assert len(relatorio.pendentes) == 1

    def test_sem_documento(self, relatorio) -> None:
        assert len(relatorio.sem_documento) == 1

    def test_percentual_conciliado(self, relatorio) -> None:
        # 2 conciliados de 6 = 33.33%
        assert relatorio.percentual_conciliado == pytest.approx(33.33)

    def test_relatorio_vazio(self) -> None:
        r = RelatorioConciliacao(
            empresa_id=uuid4(),
            periodo_inicio=date(2026, 7, 1),
            periodo_fim=date(2026, 7, 31),
        )
        assert r.total_itens == 0
        assert r.percentual_conciliado == 0.0


# =============================================================
# BANK STATEMENT PORT — CONTRATO
# =============================================================

class TestBankStatementPort:
    def test_implementacao_minima_satisfaz_protocolo(self) -> None:
        """Verifica que um adapter mínimo satisfaz o Protocol."""
        from pathlib import Path

        class FakeAdapter:
            def importar(self, fonte, empresa_id, id_importacao) -> list:
                return []

            def detectar_conta(self, fonte) -> ContaBancaria | None:
                return None

        assert isinstance(FakeAdapter(), BankStatementPort)

    def test_implementacao_incompleta_nao_satisfaz_protocolo(self) -> None:
        """Um objeto sem os métodos necessários não satisfaz o Protocol."""
        class Incompleto:
            pass

        assert not isinstance(Incompleto(), BankStatementPort)
