"""Motor de Apuração Tributária — Emenda E-09, Etapa 4.

Apura ICMS, PIS e COFINS a partir dos campos fiscais da NF-e.
100% determinístico. Zero dependência de IA.

Referências:
- RICMS (por estado — simplificado aqui para SP como base)
- Lei 10.637/2002 (PIS não-cumulativo)
- Lei 10.833/2003 (COFINS não-cumulativo)
- Lei 9.718/1998 (PIS/COFINS cumulativo — Lucro Presumido)
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    NaturezaLancamento,
    Split,
)


# =============================================================
# ENUMERAÇÕES TRIBUTÁRIAS
# =============================================================

class RegimeTributario(str, Enum):
    SIMPLES_NACIONAL        = "simples_nacional"
    LUCRO_PRESUMIDO         = "lucro_presumido"
    LUCRO_REAL              = "lucro_real"


class RegimePisCofins(str, Enum):
    CUMULATIVO              = "cumulativo"       # Lucro Presumido / Simples
    NAO_CUMULATIVO          = "nao_cumulativo"   # Lucro Real


class SituacaoTributariaICMS(str, Enum):
    """CST de ICMS simplificado (principais situações)."""
    TRIBUTADO_INTEGRAL      = "00"  # Tributado integralmente
    TRIBUTADO_REDUCAO_BASE  = "20"  # Com redução de base de cálculo
    ISENTO                  = "40"  # Isento
    NAO_TRIBUTADO           = "41"  # Não tributado
    SUBSTITUICAO_TRIBUTARIA = "10"  # Com cobrança por ST


class SituacaoTributariaPisCofins(str, Enum):
    """CST de PIS/COFINS simplificado."""
    OPERACAO_TRIBUTAVEL     = "01"  # Alíquota básica
    OPERACAO_TRIBUTAVEL_DIF = "02"  # Alíquota diferenciada
    OPERACAO_ISENTA         = "06"  # Isenta
    OPERACAO_SEM_INCIDENCIA = "07"  # Sem incidência
    OUTRAS                  = "99"  # Outras operações


# =============================================================
# VALUE OBJECTS TRIBUTÁRIOS
# =============================================================

@dataclass(frozen=True)
class AliquotaICMS:
    """Alíquota de ICMS com possível redução de base de cálculo."""
    percentual: Decimal         # ex: Decimal("12.00") = 12%
    reducao_base: Decimal = Decimal("0.00")  # % de redução da BC

    @property
    def percentual_efetivo(self) -> Decimal:
        """Alíquota efetiva após redução de base."""
        fator = (Decimal("100") - self.reducao_base) / Decimal("100")
        return (self.percentual * fator).quantize(Decimal("0.0001"), ROUND_HALF_UP)


@dataclass(frozen=True)
class AliquotaPisCofins:
    """Alíquotas de PIS e COFINS."""
    pis: Decimal                # ex: Decimal("1.65") = 1,65%
    cofins: Decimal             # ex: Decimal("7.60") = 7,60%


# Alíquotas padrão por regime
ALIQUOTAS_PADRAO = {
    RegimePisCofins.NAO_CUMULATIVO: AliquotaPisCofins(
        pis=Decimal("1.65"),
        cofins=Decimal("7.60"),
    ),
    RegimePisCofins.CUMULATIVO: AliquotaPisCofins(
        pis=Decimal("0.65"),
        cofins=Decimal("3.00"),
    ),
}


# =============================================================
# RESULTADO DA APURAÇÃO
# =============================================================

@dataclass
class ResultadoTributario:
    """Resultado da apuração tributária de um documento."""

    # ICMS
    base_calculo_icms: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    valor_icms: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    icms_recuperavel: bool = False      # True = crédito (entrada), False = débito (saída)
    cst_icms: str | None = None

    # PIS
    base_calculo_pis: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    valor_pis: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    pis_recuperavel: bool = False
    cst_pis: str | None = None

    # COFINS
    base_calculo_cofins: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    valor_cofins: Dinheiro = field(default_factory=lambda: Dinheiro(Decimal("0")))
    cofins_recuperavel: bool = False
    cst_cofins: str | None = None

    # Splits contábeis gerados
    splits_tributarios: list[Split] = field(default_factory=list)

    # Diagnóstico
    observacoes: list[str] = field(default_factory=list)
    requer_revisao: bool = False

    @property
    def carga_tributaria_total(self) -> Dinheiro:
        return Dinheiro(
            self.valor_icms.valor + self.valor_pis.valor + self.valor_cofins.valor
        )


# =============================================================
# PLANO DE CONTAS TRIBUTÁRIO (padrão — parametrizável)
# =============================================================

CONTAS_TRIBUTARIAS_PADRAO = {
    # ICMS
    "icms_a_recuperar":         CodigoConta("1.1.02.001"),  # Ativo — ICMS a recuperar
    "icms_a_recolher":          CodigoConta("2.1.03.001"),  # Passivo — ICMS a recolher
    "despesa_icms_st":          CodigoConta("4.1.02.001"),  # Despesa — ICMS-ST

    # PIS
    "pis_a_recuperar":          CodigoConta("1.1.02.002"),  # Ativo — PIS a recuperar
    "pis_a_recolher":           CodigoConta("2.1.03.002"),  # Passivo — PIS a recolher

    # COFINS
    "cofins_a_recuperar":       CodigoConta("1.1.02.003"),  # Ativo — COFINS a recuperar
    "cofins_a_recolher":        CodigoConta("2.1.03.003"),  # Passivo — COFINS a recolher

    # Conta transitória para débito do fornecedor
    "fornecedores":             CodigoConta("2.1.01.001"),
}


# =============================================================
# MOTOR DE APURAÇÃO
# =============================================================

class TaxEngine:
    """
    Motor determinístico de apuração tributária.
    Entradas: campos fiscais da NF-e + configuração da empresa.
    Saídas: valores calculados + splits contábeis prontos para o lançamento.
    """

    def __init__(
        self,
        regime_tributario: RegimeTributario,
        regime_pis_cofins: RegimePisCofins,
        contas: Optional[dict[str, CodigoConta]] = None,
    ):
        self.regime = regime_tributario
        self.regime_pis_cofins = regime_pis_cofins
        self.contas = contas or CONTAS_TRIBUTARIAS_PADRAO

    def apurar(
        self,
        valor_produtos: Dinheiro,
        cst_icms: str | None = None,
        aliquota_icms: Decimal | None = None,
        reducao_base_icms: Decimal = Decimal("0"),
        cst_pis: str | None = None,
        aliquota_pis: Decimal | None = None,
        cst_cofins: str | None = None,
        aliquota_cofins: Decimal | None = None,
        e_entrada: bool = True,  # True = NF-e de compra, False = venda
    ) -> ResultadoTributario:
        """Apura tributos e gera splits contábeis."""

        resultado = ResultadoTributario()

        # Simples Nacional: sem crédito de PIS/COFINS e ICMS
        if self.regime == RegimeTributario.SIMPLES_NACIONAL:
            resultado.observacoes.append(
                "Empresa no Simples Nacional: sem aproveitamento de créditos "
                "de ICMS, PIS e COFINS."
            )
            return resultado

        # ── ICMS ──────────────────────────────────────────────────────────
        resultado.cst_icms = cst_icms
        if cst_icms and aliquota_icms:
            resultado.base_calculo_icms, resultado.valor_icms = self._calcular_icms(
                valor_produtos, cst_icms, aliquota_icms, reducao_base_icms
            )
            resultado.icms_recuperavel = e_entrada and cst_icms in (
                SituacaoTributariaICMS.TRIBUTADO_INTEGRAL.value,
                SituacaoTributariaICMS.TRIBUTADO_REDUCAO_BASE.value,
            )

        # ── PIS ───────────────────────────────────────────────────────────
        resultado.cst_pis = cst_pis
        aliquota_pis_efetiva = aliquota_pis or (
            ALIQUOTAS_PADRAO[self.regime_pis_cofins].pis
            if cst_pis == SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL.value
            else None
        )
        if cst_pis and aliquota_pis_efetiva:
            resultado.base_calculo_pis, resultado.valor_pis = self._calcular_contribuicao(
                valor_produtos, cst_pis, aliquota_pis_efetiva
            )
            resultado.pis_recuperavel = (
                e_entrada
                and self.regime_pis_cofins == RegimePisCofins.NAO_CUMULATIVO
                and cst_pis in (
                    SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL.value,
                    SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL_DIF.value,
                )
            )

        # ── COFINS ────────────────────────────────────────────────────────
        resultado.cst_cofins = cst_cofins
        aliquota_cofins_efetiva = aliquota_cofins or (
            ALIQUOTAS_PADRAO[self.regime_pis_cofins].cofins
            if cst_cofins == SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL.value
            else None
        )
        if cst_cofins and aliquota_cofins_efetiva:
            resultado.base_calculo_cofins, resultado.valor_cofins = self._calcular_contribuicao(
                valor_produtos, cst_cofins, aliquota_cofins_efetiva
            )
            resultado.cofins_recuperavel = (
                e_entrada
                and self.regime_pis_cofins == RegimePisCofins.NAO_CUMULATIVO
                and cst_cofins in (
                    SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL.value,
                    SituacaoTributariaPisCofins.OPERACAO_TRIBUTAVEL_DIF.value,
                )
            )

        # ── Gerar splits contábeis ────────────────────────────────────────
        resultado.splits_tributarios = self._gerar_splits(resultado)
        return resultado

    # ── Cálculos ──────────────────────────────────────────────────────────

    def _calcular_icms(
        self,
        base: Dinheiro,
        cst: str,
        aliquota: Decimal,
        reducao: Decimal,
    ) -> tuple[Dinheiro, Dinheiro]:

        if cst in (
            SituacaoTributariaICMS.ISENTO.value,
            SituacaoTributariaICMS.NAO_TRIBUTADO.value,
        ):
            return Dinheiro(Decimal("0")), Dinheiro(Decimal("0"))

        aliq_efetiva = AliquotaICMS(aliquota, reducao)
        bc = base.valor * (Decimal("100") - reducao) / Decimal("100")
        bc = bc.quantize(Decimal("0.01"), ROUND_HALF_UP)
        valor = (bc * aliq_efetiva.percentual / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        return Dinheiro(bc), Dinheiro(valor)

    def _calcular_contribuicao(
        self,
        base: Dinheiro,
        cst: str,
        aliquota: Decimal,
    ) -> tuple[Dinheiro, Dinheiro]:

        if cst in (
            SituacaoTributariaPisCofins.OPERACAO_ISENTA.value,
            SituacaoTributariaPisCofins.OPERACAO_SEM_INCIDENCIA.value,
        ):
            return Dinheiro(Decimal("0")), Dinheiro(Decimal("0"))

        valor = (base.valor * aliquota / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        return base, Dinheiro(valor)

    def _gerar_splits(self, r: ResultadoTributario) -> list[Split]:
        splits: list[Split] = []

        # ICMS
        if r.valor_icms.valor > 0:
            if r.icms_recuperavel:
                # Entrada: débito em ICMS a Recuperar
                splits.append(Split(
                    conta=self.contas["icms_a_recuperar"],
                    natureza=NaturezaLancamento.DEBITO,
                    valor=r.valor_icms,
                    descricao=f"ICMS a recuperar (CST {r.cst_icms})",
                ))
            else:
                # Saída: crédito em ICMS a Recolher
                splits.append(Split(
                    conta=self.contas["icms_a_recolher"],
                    natureza=NaturezaLancamento.CREDITO,
                    valor=r.valor_icms,
                    descricao=f"ICMS a recolher (CST {r.cst_icms})",
                ))

        # PIS
        if r.valor_pis.valor > 0:
            conta = (
                self.contas["pis_a_recuperar"]
                if r.pis_recuperavel
                else self.contas["pis_a_recolher"]
            )
            natureza = (
                NaturezaLancamento.DEBITO
                if r.pis_recuperavel
                else NaturezaLancamento.CREDITO
            )
            splits.append(Split(
                conta=conta,
                natureza=natureza,
                valor=r.valor_pis,
                descricao=f"PIS {'a recuperar' if r.pis_recuperavel else 'a recolher'}",
            ))

        # COFINS
        if r.valor_cofins.valor > 0:
            conta = (
                self.contas["cofins_a_recuperar"]
                if r.cofins_recuperavel
                else self.contas["cofins_a_recolher"]
            )
            natureza = (
                NaturezaLancamento.DEBITO
                if r.cofins_recuperavel
                else NaturezaLancamento.CREDITO
            )
            splits.append(Split(
                conta=conta,
                natureza=natureza,
                valor=r.valor_cofins,
                descricao=f"COFINS {'a recuperar' if r.cofins_recuperavel else 'a recolher'}",
            ))

        return splits
