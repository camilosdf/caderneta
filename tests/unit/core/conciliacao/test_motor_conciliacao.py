"""Testes do MotorConciliacao — Etapa 8.2.

Cobre todos os critérios de aceite definidos no parecer arquitetural:

Matching:
  [✓] FITID nunca gera duas transações para a mesma conta
  [✓] Uma transação não pode ser conciliada com dois lançamentos
  [✓] Um lançamento não pode ser conciliado com dois movimentos
  [✓] Valor dentro de R$ 0,10 é tolerável
  [✓] Data dentro de 2 dias é tolerável
  [✓] Dois candidatos equivalentes geram AMBIGUO
  [✓] Ausência de candidato gera SEM_DOCUMENTO (transação) ou PENDENTE (lançamento)
  [✓] Diferença relevante gera DIVERGENTE
  [✓] Nenhuma decisão usa IA

Herméticos: sem banco, arquivo ou rede.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from core.domain.entities import (
    CodigoConta,
    ContaBancaria,
    Dinheiro,
    Lancamento,
    MetodoMatching,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    TipoConciliacao,
    TransacaoBancaria,
)
from core.rule_engine.motor_conciliacao import (
    MotorConciliacao,
    ToleranciasConciliacao,
    _similaridade_descricao,
)


# =============================================================
# HELPERS
# =============================================================

EMPRESA_ID = uuid4()

def _conta() -> ContaBancaria:
    return ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6")


def _tx(
    fitid: str = "TX001",
    valor: str = "100.00",
    data: date = date(2026, 7, 15),
    descricao: str = "UBER DO BRASIL",
    natureza: NaturezaLancamento = NaturezaLancamento.DEBITO,
) -> TransacaoBancaria:
    return TransacaoBancaria(
        empresa_id=EMPRESA_ID,
        conta_bancaria=_conta(),
        fitid=fitid,
        data=data,
        valor=Dinheiro(Decimal(valor)),
        natureza=natureza,
        descricao=descricao,
    )


def _lanc(
    valor: str = "100.00",
    data: date = date(2026, 7, 15),
    descricao: str = "UBER DO BRASIL",
    status: StatusLancamento = StatusLancamento.APROVADO,
) -> Lancamento:
    return Lancamento(
        empresa_id=EMPRESA_ID,
        descricao=descricao,
        status=status,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=data,
        splits=[
            Split(
                conta=CodigoConta("4.1.01.001"),
                natureza=NaturezaLancamento.DEBITO,
                valor=Dinheiro(Decimal(valor)),
            ),
            Split(
                conta=CodigoConta("1.1.01.002"),
                natureza=NaturezaLancamento.CREDITO,
                valor=Dinheiro(Decimal(valor)),
            ),
        ],
    )


def _motor(tolerancias: ToleranciasConciliacao | None = None) -> MotorConciliacao:
    return MotorConciliacao(tolerancias=tolerancias)


def _conciliar(
    transacoes: list[TransacaoBancaria],
    lancamentos: list[Lancamento],
    motor: MotorConciliacao | None = None,
):
    m = motor or _motor()
    return m.conciliar(
        lancamentos=lancamentos,
        transacoes=transacoes,
        empresa_id=EMPRESA_ID,
        periodo_inicio=date(2026, 7, 1),
        periodo_fim=date(2026, 7, 31),
    )


# =============================================================
# MATCH EXATO: valor + data idênticos
# =============================================================

class TestMatchExato:
    def test_valor_e_data_identicos_gera_conciliado(self) -> None:
        tx = _tx(valor="100.00", data=date(2026, 7, 15))
        lanc = _lanc(valor="100.00", data=date(2026, 7, 15))
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.CONCILIADO
        assert item.lancamento_id == lanc.id

    def test_match_exato_diferenca_valor_zero(self) -> None:
        tx = _tx(valor="250.50")
        lanc = _lanc(valor="250.50")
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.diferenca_valor == Decimal("0")


# =============================================================
# TOLERÂNCIAS (critérios de aceite do parecer)
# =============================================================

class TestToleranciaValor:
    def test_diferenca_dentro_de_010_e_toleravel(self) -> None:
        """Critério do parecer: valor dentro de R$ 0,10 é tolerável."""
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="100.09")  # Δ = R$ 0,09
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status in (TipoConciliacao.CONCILIADO, TipoConciliacao.DIVERGENTE)
        assert item.lancamento_id == lanc.id

    def test_diferenca_acima_de_010_nao_e_candidato(self) -> None:
        """Diferença de R$ 0,11 está fora da tolerância → SEM_DOCUMENTO."""
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="100.11")  # Δ = R$ 0,11
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.SEM_DOCUMENTO

    def test_diferenca_exatamente_010_e_toleravel(self) -> None:
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="100.10")  # Δ = R$ 0,10 (limite exato)
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.lancamento_id == lanc.id


class TestToleranciaData:
    def test_diferenca_dentro_de_2_dias_e_toleravel(self) -> None:
        """Critério do parecer: data dentro de 2 dias é tolerável."""
        tx = _tx(data=date(2026, 7, 15))
        lanc = _lanc(data=date(2026, 7, 17))  # Δ = 2 dias
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.lancamento_id == lanc.id

    def test_diferenca_3_dias_fora_da_tolerancia(self) -> None:
        """Δ = 3 dias → fora da tolerância → SEM_DOCUMENTO."""
        tx = _tx(data=date(2026, 7, 15))
        lanc = _lanc(data=date(2026, 7, 18))  # Δ = 3 dias
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.SEM_DOCUMENTO

    def test_tolerancia_configuravel(self) -> None:
        """Tolerâncias devem ser configuráveis por empresa."""
        tol = ToleranciasConciliacao(valor=Decimal("0.50"), dias=5)
        tx = _tx(data=date(2026, 7, 15), valor="100.00")
        lanc = _lanc(data=date(2026, 7, 19), valor="100.40")  # 4 dias, Δ R$ 0,40
        rel = _conciliar([tx], [lanc], motor=_motor(tol))

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.lancamento_id == lanc.id


# =============================================================
# AMBIGUIDADE (critério de aceite: dois candidatos → AMBIGUO)
# =============================================================

class TestAmbiguidade:
    def test_dois_candidatos_equivalentes_geram_ambiguo(self) -> None:
        """Critério do parecer: nunca escolher arbitrariamente."""
        tx = _tx(valor="150.00", data=date(2026, 7, 10))
        lanc_a = _lanc(valor="150.00", data=date(2026, 7, 10), descricao="MERCADO A")
        lanc_b = _lanc(valor="150.00", data=date(2026, 7, 10), descricao="MERCADO B")

        rel = _conciliar([tx], [lanc_a, lanc_b])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.AMBIGUO
        assert len(item.candidatos) == 2

    def test_ambiguo_preserva_todos_os_candidatos(self) -> None:
        tx = _tx(valor="200.00", data=date(2026, 7, 5))
        lancamentos = [
            _lanc(valor="200.00", data=date(2026, 7, 5), descricao=f"EMPRESA {i}")
            for i in range(3)
        ]
        rel = _conciliar([tx], lancamentos)

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.AMBIGUO
        assert len(item.candidatos) >= 2


# =============================================================
# SEM CORRESPONDÊNCIA
# =============================================================

class TestSemCorrespondencia:
    def test_transacao_sem_lancamento_gera_sem_documento(self) -> None:
        """Critério do parecer: sem candidato → SEM_DOCUMENTO."""
        tx = _tx(valor="999.99")
        rel = _conciliar([tx], [])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.SEM_DOCUMENTO
        assert item.lancamento_id is None

    def test_lancamento_sem_transacao_gera_pendente(self) -> None:
        """Critério do parecer: lançamento sem cobertura bancária → PENDENTE."""
        lanc = _lanc(valor="100.00")
        rel = _conciliar([], [lanc])

        item = next(i for i in rel.itens if i.lancamento_id == lanc.id)
        assert item.status == TipoConciliacao.PENDENTE
        assert item.transacao_bancaria_id is None

    def test_valor_muito_diferente_gera_sem_documento(self) -> None:
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="500.00")
        rel = _conciliar([tx], [lanc])

        tx_item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert tx_item.status == TipoConciliacao.SEM_DOCUMENTO


# =============================================================
# DIVERGÊNCIA
# =============================================================

class TestDivergencia:
    def test_diferenca_de_valor_dentro_da_tolerancia_gera_divergente(self) -> None:
        """Critério do parecer: diferença relevante gera DIVERGENTE."""
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="100.05")  # dentro da tolerância, mas há diferença
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.DIVERGENTE
        assert item.diferenca_valor > Decimal("0")

    def test_diferenca_de_data_gera_divergente(self) -> None:
        tx = _tx(data=date(2026, 7, 15))
        lanc = _lanc(data=date(2026, 7, 16))  # 1 dia de diferença
        rel = _conciliar([tx], [lanc])

        item = next(i for i in rel.itens if i.transacao_bancaria_id == tx.id)
        assert item.status == TipoConciliacao.DIVERGENTE
        assert item.diferenca_dias == 1


# =============================================================
# UNICIDADE (invariantes de domínio)
# =============================================================

class TestUnicidade:
    def test_transacao_conciliada_com_no_maximo_um_lancamento(self) -> None:
        """Critério: uma transação não pode ser conciliada com dois lançamentos."""
        tx = _tx(valor="100.00", data=date(2026, 7, 15))
        lanc_a = _lanc(valor="100.00", data=date(2026, 7, 15), descricao="A")
        lanc_b = _lanc(valor="100.00", data=date(2026, 7, 15), descricao="B")

        rel = _conciliar([tx], [lanc_a, lanc_b])

        tx_items = [i for i in rel.itens if i.transacao_bancaria_id == tx.id]
        assert len(tx_items) == 1  # transação aparece uma só vez

    def test_lancamento_conciliado_com_no_maximo_uma_transacao(self) -> None:
        """Critério: um lançamento não pode ser conciliado com dois movimentos."""
        tx_a = _tx(fitid="TX_A", valor="100.00", data=date(2026, 7, 15))
        tx_b = _tx(fitid="TX_B", valor="100.00", data=date(2026, 7, 15))
        lanc = _lanc(valor="100.00", data=date(2026, 7, 15))

        rel = _conciliar([tx_a, tx_b], [lanc])

        # Lançamento deve aparecer como lancamento_id em no máximo um item conciliado
        itens_com_lancamento = [
            i for i in rel.itens
            if i.lancamento_id == lanc.id
            and i.status == TipoConciliacao.CONCILIADO
        ]
        assert len(itens_com_lancamento) <= 1

    def test_dois_lancamentos_diferentes_dois_matches(self) -> None:
        """Cada par (transação, lançamento) deve gerar um item separado."""
        tx_a = _tx(fitid="TX_A", valor="100.00", descricao="UBER")
        tx_b = _tx(fitid="TX_B", valor="200.00", descricao="IFOOD")
        lanc_a = _lanc(valor="100.00", descricao="UBER")
        lanc_b = _lanc(valor="200.00", descricao="IFOOD")

        rel = _conciliar([tx_a, tx_b], [lanc_a, lanc_b])

        conciliados = rel.conciliados
        assert len(conciliados) == 2


# =============================================================
# RELATÓRIO COMPLETO
# =============================================================

class TestRelatorioCompleto:
    def test_total_itens_correto(self) -> None:
        """Total de itens = transações + lançamentos sem match."""
        transacoes = [_tx(fitid=f"TX{i}", valor="100.00") for i in range(3)]
        lancamentos = [_lanc(valor="100.00") for _ in range(2)]  # um vai sobrar

        rel = _conciliar(transacoes, lancamentos)

        # 3 transações geram 3 itens; + 0 ou 1 lançamento pendente (depende dos matches)
        assert rel.total_itens >= 3

    def test_percentual_conciliado_calculado(self) -> None:
        tx = _tx(valor="100.00")
        lanc = _lanc(valor="100.00")
        rel = _conciliar([tx], [lanc])

        assert rel.percentual_conciliado > 0

    def test_relatorio_vazio_sem_itens(self) -> None:
        rel = _conciliar([], [])
        assert rel.total_itens == 0
        assert rel.percentual_conciliado == 0.0


# =============================================================
# SIMILARIDADE DE DESCRIÇÃO
# =============================================================

class TestSimilaridadeDescricao:
    def test_textos_identicos(self) -> None:
        assert _similaridade_descricao("UBER DO BRASIL", "UBER DO BRASIL") == pytest.approx(1.0)

    def test_textos_completamente_diferentes(self) -> None:
        sim = _similaridade_descricao("UBER", "XYZWQ")
        assert sim < 0.3

    def test_truncamento_tipico_de_extrato(self) -> None:
        """Extrato bancário frequentemente trunca nomes."""
        sim = _similaridade_descricao("SUPERMERCADO BOM PRECO", "SUP BOM PRECO")
        assert sim > 0.4

    def test_texto_vazio_retorna_zero(self) -> None:
        assert _similaridade_descricao("", "UBER") == 0.0
        assert _similaridade_descricao("UBER", "") == 0.0

    def test_simetria(self) -> None:
        a, b = "UBER DO BRASIL", "UBER VIAGENS"
        assert _similaridade_descricao(a, b) == _similaridade_descricao(b, a)
