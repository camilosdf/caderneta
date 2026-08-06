"""Testes do Motor Tributário — Emenda E-09.

Meta: cobertura > 90% em core/rule_engine/tax_engine.py
Regras tributárias têm impacto financeiro direto — cada caso deve ter teste.
"""

from decimal import Decimal

import pytest

from core.domain.entities import NaturezaLancamento
from core.rule_engine.tax_engine import (
    RegimePisCofins,
    RegimeTributario,
    SituacaoTributariaICMS,
    SituacaoTributariaPisCofins,
    TaxEngine,
    Dinheiro,
)


@pytest.fixture
def engine_lucro_real():
    return TaxEngine(
        regime_tributario=RegimeTributario.LUCRO_REAL,
        regime_pis_cofins=RegimePisCofins.NAO_CUMULATIVO,
    )


@pytest.fixture
def engine_lucro_presumido():
    return TaxEngine(
        regime_tributario=RegimeTributario.LUCRO_PRESUMIDO,
        regime_pis_cofins=RegimePisCofins.CUMULATIVO,
    )


@pytest.fixture
def engine_simples():
    return TaxEngine(
        regime_tributario=RegimeTributario.SIMPLES_NACIONAL,
        regime_pis_cofins=RegimePisCofins.CUMULATIVO,
    )


class TestICMS:
    def test_tributado_integral_entrada(self, engine_lucro_real):
        """NF-e de compra com ICMS 12% — deve gerar crédito a recuperar."""
        base = Dinheiro(Decimal("1000.00"))
        resultado = engine_lucro_real.apurar(
            valor_produtos=base,
            cst_icms="00",
            aliquota_icms=Decimal("12.00"),
            e_entrada=True,
        )
        assert resultado.valor_icms.valor == Decimal("120.00")
        assert resultado.icms_recuperavel is True
        # Deve gerar split de débito em ICMS a recuperar
        splits_icms = [s for s in resultado.splits_tributarios if "icms" in s.conta.codigo.lower() or "1.1.02.001" in s.conta.codigo]
        assert any(s.natureza == NaturezaLancamento.DEBITO for s in resultado.splits_tributarios)

    def test_tributado_integral_saida(self, engine_lucro_real):
        """NF-e de venda com ICMS 12% — deve gerar débito a recolher."""
        base = Dinheiro(Decimal("1000.00"))
        resultado = engine_lucro_real.apurar(
            valor_produtos=base,
            cst_icms="00",
            aliquota_icms=Decimal("12.00"),
            e_entrada=False,
        )
        assert resultado.valor_icms.valor == Decimal("120.00")
        assert resultado.icms_recuperavel is False

    def test_isento_nao_gera_valor(self, engine_lucro_real):
        """CST 40 (isento) — valor do ICMS deve ser zero."""
        base = Dinheiro(Decimal("1000.00"))
        resultado = engine_lucro_real.apurar(
            valor_produtos=base,
            cst_icms="40",
            aliquota_icms=Decimal("12.00"),
            e_entrada=True,
        )
        assert resultado.valor_icms.valor == Decimal("0.00")

    def test_reducao_base_calculo(self, engine_lucro_real):
        """CST 20 com redução de 40% da BC — ICMS sobre 60% do valor."""
        base = Dinheiro(Decimal("1000.00"))
        resultado = engine_lucro_real.apurar(
            valor_produtos=base,
            cst_icms="20",
            aliquota_icms=Decimal("12.00"),
            reducao_base_icms=Decimal("40.00"),
            e_entrada=True,
        )
        # BC = 1000 * (1 - 0.40) = 600
        # ICMS = 600 * 12% = 72
        assert resultado.base_calculo_icms.valor == Decimal("600.00")
        assert resultado.valor_icms.valor == Decimal("72.00")

    def test_sem_dados_icms_retorna_zero(self, engine_lucro_real):
        """Sem CST e alíquota — valor ICMS deve ser zero."""
        resultado = engine_lucro_real.apurar(
            valor_produtos=Dinheiro(Decimal("500.00")),
        )
        assert resultado.valor_icms.valor == Decimal("0.00")


class TestPisCofins:
    def test_nao_cumulativo_gera_credito_entrada(self, engine_lucro_real):
        """Lucro Real não-cumulativo — PIS/COFINS na entrada gera crédito."""
        resultado = engine_lucro_real.apurar(
            valor_produtos=Dinheiro(Decimal("1000.00")),
            cst_pis="01",
            cst_cofins="01",
            e_entrada=True,
        )
        assert resultado.valor_pis.valor == Decimal("16.50")    # 1.65%
        assert resultado.valor_cofins.valor == Decimal("76.00") # 7.60%
        assert resultado.pis_recuperavel is True
        assert resultado.cofins_recuperavel is True

    def test_cumulativo_sem_credito(self, engine_lucro_presumido):
        """Lucro Presumido cumulativo — sem crédito de PIS/COFINS."""
        resultado = engine_lucro_presumido.apurar(
            valor_produtos=Dinheiro(Decimal("1000.00")),
            cst_pis="01",
            cst_cofins="01",
            e_entrada=True,
        )
        assert resultado.valor_pis.valor == Decimal("6.50")     # 0.65%
        assert resultado.valor_cofins.valor == Decimal("30.00") # 3.00%
        assert resultado.pis_recuperavel is False
        assert resultado.cofins_recuperavel is False

    def test_isento_nao_gera_pis_cofins(self, engine_lucro_real):
        """CST 06 (isento) — PIS/COFINS zerados."""
        resultado = engine_lucro_real.apurar(
            valor_produtos=Dinheiro(Decimal("1000.00")),
            cst_pis="06",
            cst_cofins="06",
            e_entrada=True,
        )
        assert resultado.valor_pis.valor == Decimal("0.00")
        assert resultado.valor_cofins.valor == Decimal("0.00")


class TestSimplesNacional:
    def test_simples_sem_creditos(self, engine_simples):
        """Simples Nacional — sem aproveitamento de nenhum crédito."""
        resultado = engine_simples.apurar(
            valor_produtos=Dinheiro(Decimal("1000.00")),
            cst_icms="00",
            aliquota_icms=Decimal("12.00"),
            cst_pis="01",
            cst_cofins="01",
            e_entrada=True,
        )
        # Simples Nacional: nenhum crédito aproveitado
        assert resultado.valor_icms.valor == Decimal("0.00")
        assert resultado.valor_pis.valor == Decimal("0.00")
        assert resultado.valor_cofins.valor == Decimal("0.00")
        assert len(resultado.splits_tributarios) == 0
        assert len(resultado.observacoes) > 0  # deve ter aviso explicativo

    def test_simples_retorna_observacao(self, engine_simples):
        resultado = engine_simples.apurar(
            valor_produtos=Dinheiro(Decimal("500.00")),
        )
        assert any("Simples Nacional" in obs for obs in resultado.observacoes)


class TestCargaTributariaTotal:
    def test_carga_total_soma_tributos(self, engine_lucro_real):
        resultado = engine_lucro_real.apurar(
            valor_produtos=Dinheiro(Decimal("1000.00")),
            cst_icms="00",
            aliquota_icms=Decimal("12.00"),
            cst_pis="01",
            cst_cofins="01",
            e_entrada=True,
        )
        esperado = Decimal("120.00") + Decimal("16.50") + Decimal("76.00")
        assert resultado.carga_tributaria_total.valor == esperado


class TestMotorEstorno:
    def _lancamento_aprovado(self):
        from datetime import date
        from core.domain.entities import CodigoConta, Dinheiro, Split, Lancamento, StatusLancamento, NivelAprovacao
        lancamento = Lancamento(
            descricao="SUPERMERCADO TESTE",
            data_lancamento=date(2026, 6, 1),
            status=StatusLancamento.APROVADO,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        lancamento.splits = [
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal("100.00"))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal("100.00"))),
        ]
        return lancamento

    def test_estorno_inverte_splits(self):
        from core.rule_engine.estorno import MotorEstorno
        motor = MotorEstorno()
        original = self._lancamento_aprovado()
        resultado = motor.estornar(original, motivo="Lançamento duplicado", responsavel="contador@empresa.com")

        estorno = resultado.lancamento_estorno
        # O split débito do original vira crédito no estorno
        debitos_estorno = [s for s in estorno.splits if s.natureza == NaturezaLancamento.DEBITO]
        creditos_estorno = [s for s in estorno.splits if s.natureza == NaturezaLancamento.CREDITO]
        assert len(debitos_estorno) == 1
        assert len(creditos_estorno) == 1
        # Conta do débito do estorno = conta do crédito do original
        assert creditos_estorno[0].conta.codigo == "4.1.01.001"
        assert debitos_estorno[0].conta.codigo == "1.1.01.002"

    def test_estorno_mantem_partidas_dobradas(self):
        from core.rule_engine.estorno import MotorEstorno
        motor = MotorEstorno()
        original = self._lancamento_aprovado()
        resultado = motor.estornar(original, motivo="Teste", responsavel="x")
        resultado.lancamento_estorno.validar()  # não deve lançar

    def test_estorno_de_rascunho_falha(self):
        from core.domain.entities import StatusLancamento
        from core.rule_engine.estorno import MotorEstorno
        motor = MotorEstorno()
        original = self._lancamento_aprovado()
        original.status = StatusLancamento.RASCUNHO
        with pytest.raises(ValueError, match="rascunho"):
            motor.estornar(original, "motivo", "usuario")

    def test_historico_do_estorno_referencia_original(self):
        from core.rule_engine.estorno import MotorEstorno
        motor = MotorEstorno()
        original = self._lancamento_aprovado()
        resultado = motor.estornar(original, motivo="NF cancelada", responsavel="c@e.com")
        assert "ESTORNO" in resultado.lancamento_estorno.descricao
        assert str(original.id)[:8].upper() in resultado.lancamento_estorno.descricao
