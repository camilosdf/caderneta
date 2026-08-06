"""Testes do Modelo de Domínio — Etapa 1.

Meta: cobertura > 90% em core/domain/.
Toda invariante contábil deve ter pelo menos um teste.

v0.3.2 — Correções:
- CNPJ: testes atualizados com CNPJs que passam no algoritmo RF correto
- CodigoConta: removida contradição (nível 1 é válido — conta raiz sintética)
- datetime: usando datetime.now(UTC) em vez de utcnow()
- Ruff E741: variável 'l' renomeada para 'lancamento'
- Ruff B017: pytest.raises com match específico
"""

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from core.domain.entities import (
    CNPJ,
    CodigoConta,
    ConfidenceScore,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    PeriodoContabil,
    Split,
    StatusLancamento,
    StatusPeriodo,
    Usuario,
)

UTC = timezone.utc


# =============================================================
# DINHEIRO
# =============================================================
class TestDinheiro:
    def test_cria_valor_positivo(self):
        d = Dinheiro(Decimal("100.00"))
        assert d.valor == Decimal("100.00")
        assert d.moeda == "BRL"

    def test_aceita_valor_zero(self):
        d = Dinheiro(Decimal("0.00"))
        assert d.valor == Decimal("0.00")

    def test_rejeita_valor_negativo(self):
        with pytest.raises(ValueError, match="negativo"):
            Dinheiro(Decimal("-1.00"))

    def test_soma_mesma_moeda(self):
        resultado = Dinheiro(Decimal("50.00")) + Dinheiro(Decimal("30.00"))
        assert resultado.valor == Decimal("80.00")

    def test_rejeita_soma_moedas_diferentes(self):
        brl = Dinheiro(Decimal("50.00"), "BRL")
        usd = Dinheiro(Decimal("10.00"), "USD")
        with pytest.raises(ValueError, match="incompatíveis"):
            _ = brl + usd

    def test_imutavel(self):
        d = Dinheiro(Decimal("100.00"))
        with pytest.raises((AttributeError, TypeError)):
            d.valor = Decimal("200.00")  # type: ignore[misc]

    def test_str_formatado(self):
        assert str(Dinheiro(Decimal("1234.56"))) == "BRL 1,234.56"


# =============================================================
# CNPJ
# =============================================================
class TestCNPJ:
    # CNPJs válidos verificados pelo algoritmo da Receita Federal
    CNPJ_VALIDO        = "11222333000181"   # dígitos 8 e 1
    CNPJ_VALIDO_PONTOS = "11.222.333/0001-81"
    CNPJ_PETROBRAS     = "33000167000101"   # CNPJ público, amplamente conhecido

    def test_aceita_cnpj_valido(self):
        c = CNPJ(self.CNPJ_VALIDO)
        assert c.numero == self.CNPJ_VALIDO

    def test_aceita_cnpj_petrobras(self):
        c = CNPJ(self.CNPJ_PETROBRAS)
        assert c.numero == self.CNPJ_PETROBRAS

    def test_limpa_pontuacao(self):
        c = CNPJ(self.CNPJ_VALIDO_PONTOS)
        assert c.numero == self.CNPJ_VALIDO

    def test_formatado(self):
        c = CNPJ(self.CNPJ_VALIDO)
        assert c.formatado() == self.CNPJ_VALIDO_PONTOS

    def test_rejeita_todos_digitos_iguais(self):
        with pytest.raises(ValueError, match="inválidos"):
            CNPJ("11111111111111")

    def test_rejeita_zeros(self):
        with pytest.raises(ValueError, match="inválidos"):
            CNPJ("00000000000000")

    def test_rejeita_tamanho_errado_curto(self):
        with pytest.raises(ValueError, match="14 dígitos"):
            CNPJ("1234567890123")

    def test_rejeita_tamanho_errado_longo(self):
        with pytest.raises(ValueError, match="14 dígitos"):
            CNPJ("123456789012345")

    def test_rejeita_digito_verificador_errado(self):
        # CNPJ válido com último dígito alterado
        with pytest.raises(ValueError, match="inválidos"):
            CNPJ("11222333000182")  # era 81, agora 82

    def test_imutavel(self):
        c = CNPJ(self.CNPJ_VALIDO)
        with pytest.raises((AttributeError, TypeError)):
            c.numero = "00000000000000"  # type: ignore[misc]


# =============================================================
# CÓDIGO DE CONTA
# =============================================================
class TestCodigoConta:
    def test_aceita_nivel_1_sintetico(self):
        """Nível 1 é a raiz do plano de contas (ex: '4' = Despesas)."""
        c = CodigoConta("4")
        assert c.nivel == 1
        assert c.e_sintetica is True

    def test_aceita_nivel_2_sintetico(self):
        c = CodigoConta("4.1")
        assert c.nivel == 2
        assert c.e_sintetica is True

    def test_aceita_nivel_3_sintetico(self):
        c = CodigoConta("4.1.01")
        assert c.nivel == 3
        assert c.e_sintetica is True

    def test_aceita_nivel_4_analitico(self):
        c = CodigoConta("4.1.01.001")
        assert c.nivel == 4
        assert c.e_sintetica is False

    def test_aceita_nivel_5_analitico(self):
        c = CodigoConta("4.1.01.001.01")
        assert c.nivel == 5
        assert c.e_sintetica is False

    def test_rejeita_codigo_vazio(self):
        with pytest.raises(ValueError):
            CodigoConta("")

    def test_rejeita_mais_de_cinco_niveis(self):
        with pytest.raises(ValueError, match="inválido"):
            CodigoConta("4.1.01.001.01.01")

    def test_rejeita_parte_nao_numerica(self):
        with pytest.raises(ValueError, match="inválido"):
            CodigoConta("4.A.01")

    def test_sintetica_nao_aceita_lancamento(self):
        c = CodigoConta("4.1.01")
        with pytest.raises(ValueError, match="sintética"):
            c.validar_para_lancamento()

    def test_analitica_aceita_lancamento(self):
        c = CodigoConta("4.1.01.001")
        c.validar_para_lancamento()  # não deve lançar


# =============================================================
# CONFIDENCE SCORE
# =============================================================
class TestConfidenceScore:
    def test_score_confiavel(self):
        s = ConfidenceScore(0.95, "valor")
        assert s.e_confiavel is True
        assert s.e_pre_aprovavel is False

    def test_score_pre_aprovavel(self):
        s = ConfidenceScore(0.99, "categoria")
        assert s.e_pre_aprovavel is True

    def test_score_exatamente_no_limite(self):
        assert ConfidenceScore(0.90, "x").e_confiavel is True
        assert ConfidenceScore(0.89, "x").e_confiavel is False

    def test_rejeita_score_acima_de_1(self):
        with pytest.raises(ValueError, match="0.0 e 1.0"):
            ConfidenceScore(1.01, "campo")

    def test_rejeita_score_negativo(self):
        with pytest.raises(ValueError, match="0.0 e 1.0"):
            ConfidenceScore(-0.1, "campo")

    def test_score_zero_valido(self):
        s = ConfidenceScore(0.0, "campo")
        assert s.e_confiavel is False


# =============================================================
# LANÇAMENTO — INVARIANTE DE PARTIDAS DOBRADAS
# =============================================================
class TestLancamento:
    def _split(self, conta: str, natureza: NaturezaLancamento, valor: str) -> Split:
        return Split(
            conta=CodigoConta(conta),
            natureza=natureza,
            valor=Dinheiro(Decimal(valor)),
        )

    def test_lancamento_equilibrado_valida(self):
        lancamento = Lancamento()
        lancamento.splits = [
            self._split("4.1.01.001", NaturezaLancamento.DEBITO, "100.00"),
            self._split("1.1.01.002", NaturezaLancamento.CREDITO, "100.00"),
        ]
        lancamento.validar()  # não deve lançar

    def test_lancamento_desequilibrado_falha(self):
        lancamento = Lancamento()
        lancamento.splits = [
            self._split("4.1.01.001", NaturezaLancamento.DEBITO, "100.00"),
            self._split("1.1.01.002", NaturezaLancamento.CREDITO, "90.00"),
        ]
        with pytest.raises(ValueError, match="desequilibradas"):
            lancamento.validar()

    def test_lancamento_sem_splits_falha(self):
        lancamento = Lancamento()
        with pytest.raises(ValueError, match="sem splits"):
            lancamento.validar()

    def test_tolerancia_centavos(self):
        """Diferença de até R$ 0,02 é tolerada (arredondamentos)."""
        lancamento = Lancamento()
        lancamento.splits = [
            self._split("4.1.01.001", NaturezaLancamento.DEBITO, "100.01"),
            self._split("1.1.01.002", NaturezaLancamento.CREDITO, "100.00"),
        ]
        lancamento.validar()  # diferença de 0.01 — dentro da tolerância

    def test_valor_total_soma_debitos(self):
        lancamento = Lancamento()
        lancamento.splits = [
            self._split("4.1.01.001", NaturezaLancamento.DEBITO, "150.00"),
            self._split("1.1.01.002", NaturezaLancamento.CREDITO, "150.00"),
        ]
        assert lancamento.valor_total.valor == Decimal("150.00")

    def test_aprovacao_nivel_1_um_aprovador(self):
        lancamento = Lancamento(
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        lancamento.aprovar("contador@empresa.com", nivel=1)
        assert lancamento.status == StatusLancamento.APROVADO
        assert lancamento.aprovado_por_1 == "contador@empresa.com"
        assert lancamento.aprovado_em_1 is not None

    def test_aprovacao_nivel_2_completa(self):
        lancamento = Lancamento(
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES,
        )
        lancamento.aprovar("contador@empresa.com", nivel=1)
        assert lancamento.status == StatusLancamento.PENDENTE  # ainda aguarda nível 2
        lancamento.aprovar("supervisor@empresa.com", nivel=2)
        assert lancamento.status == StatusLancamento.APROVADO

    def test_aprovacao_nivel_2_sem_nivel_1_falha(self):
        lancamento = Lancamento(status=StatusLancamento.PENDENTE)
        with pytest.raises(ValueError, match="nível 1"):
            lancamento.aprovar("supervisor@empresa.com", nivel=2)

    def test_aprovacao_registra_timestamp(self):
        lancamento = Lancamento(
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        antes = datetime.now(UTC)
        lancamento.aprovar("contador@empresa.com", nivel=1)
        depois = datetime.now(UTC)
        # aprovado_em_1 é aware (UTC)
        assert antes <= lancamento.aprovado_em_1 <= depois  # type: ignore[operator]


# =============================================================
# PERÍODO CONTÁBIL
# =============================================================
class TestPeriodoContabil:
    def test_fechar_periodo(self):
        periodo = PeriodoContabil(ano=2026, mes=6)
        periodo.fechar("contador@empresa.com")
        assert periodo.status == StatusPeriodo.FECHADO
        assert periodo.fechado_por == "contador@empresa.com"
        assert periodo.fechado_em is not None

    def test_fechar_periodo_ja_fechado_falha(self):
        periodo = PeriodoContabil(ano=2026, mes=6)
        periodo.fechar("contador@empresa.com")
        with pytest.raises(ValueError, match="já está fechado"):
            periodo.fechar("outro@empresa.com")

    def test_verificar_periodo_fechado_lanca_excecao(self):
        periodo = PeriodoContabil(ano=2026, mes=6)
        periodo.fechar("contador@empresa.com")
        with pytest.raises(ValueError, match="fechado"):
            periodo.verificar_aberto()

    def test_verificar_periodo_aberto_nao_lanca(self):
        periodo = PeriodoContabil(ano=2026, mes=6)
        periodo.verificar_aberto()  # não deve lançar


# =============================================================
# USUÁRIO — PAPÉIS E PERMISSÕES
# =============================================================
class TestUsuario:
    def test_contador_pode_aprovar(self):
        assert Usuario(papel="contador").pode_aprovar() is True

    def test_operador_nao_pode_aprovar(self):
        assert Usuario(papel="operador").pode_aprovar() is False

    def test_auditor_nao_pode_aprovar(self):
        assert Usuario(papel="auditor").pode_aprovar() is False

    def test_supervisor_pode_aprovar(self):
        assert Usuario(papel="supervisor").pode_aprovar() is True

    def test_supervisor_pode_fechar_periodo(self):
        assert Usuario(papel="supervisor").pode_fechar_periodo() is True

    def test_contador_nao_pode_fechar_periodo(self):
        assert Usuario(papel="contador").pode_fechar_periodo() is False

    def test_admin_pode_tudo(self):
        admin = Usuario(papel="admin")
        assert admin.pode_aprovar() is True
        assert admin.pode_aprovar_alto_valor() is True
        assert admin.pode_fechar_periodo() is True
