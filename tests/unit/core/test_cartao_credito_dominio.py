"""Testes do domínio de Cartão de Crédito — ADR 010, Fase 1.

Cobre: CartaoCredito (identidade, validação de final_numero),
CompraCartao (tipos de item), FaturaCartao (invariante de fechamento,
tolerância B2, chave de idempotência D13).
"""

from datetime import date
from decimal import Decimal

import pytest

from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    Dinheiro,
    FaturaCartao,
    StatusFechamentoFatura,
    TipoItemFatura,
)

# =============================================================
# CartaoCredito — D2, B1
# =============================================================

class TestCartaoCredito:
    def test_criacao_valida(self):
        c = CartaoCredito(
            emissor="Nubank", final_numero="1234", titular="Camilo",
            conta_codigo=CodigoConta("2.1.05.001"),
        )
        assert c.emissor == "Nubank"
        assert c.ativo is True

    def test_final_numero_deve_ter_4_digitos(self):
        with pytest.raises(ValueError):
            CartaoCredito(emissor="Nubank", final_numero="123", titular="Camilo")

    def test_final_numero_nao_aceita_numero_completo(self):
        """Nunca armazenar o número completo do cartão (Seção 24/CLAUDE.md)."""
        with pytest.raises(ValueError):
            CartaoCredito(
                emissor="Nubank", final_numero="1234567812341234", titular="Camilo",
            )

    def test_final_numero_deve_ser_numerico(self):
        with pytest.raises(ValueError):
            CartaoCredito(emissor="Nubank", final_numero="12ab", titular="Camilo")

    def test_chave_idempotencia_estavel(self):
        """Mesmos dados de identidade produzem a mesma chave (B1)."""
        c1 = CartaoCredito(emissor="Nubank", final_numero="1234", titular="Camilo")
        c1.empresa_id = c1.empresa_id  # id próprio não entra na chave de negócio
        chave1 = f"{c1.empresa_id}:{c1.emissor}:{c1.final_numero}:{c1.titular}"
        assert c1.chave_idempotencia() == chave1

    def test_chave_idempotencia_diferente_para_cartoes_diferentes(self):
        c1 = CartaoCredito(emissor="Nubank", final_numero="1234", titular="Camilo")
        c2 = CartaoCredito(emissor="Nubank", final_numero="5678", titular="Camilo")
        assert c1.chave_idempotencia() != c2.chave_idempotencia()

    def test_conta_codigo_e_referencia_textual_dt_cc_01(self):
        """DT-CC-01: conta_codigo é CodigoConta (VO textual), não FK persistida."""
        c = CartaoCredito(
            emissor="Nubank", final_numero="1234", titular="Camilo",
            conta_codigo=CodigoConta("2.1.05.001"),
        )
        assert isinstance(c.conta_codigo, CodigoConta)
        assert c.conta_codigo.codigo == "2.1.05.001"


# =============================================================
# CompraCartao — D4, D9, D10
# =============================================================

class TestCompraCartao:
    @pytest.mark.parametrize("tipo", list(TipoItemFatura))
    def test_todos_os_tipos_de_item_instanciam(self, tipo):
        item = CompraCartao(tipo=tipo, valor=Dinheiro(Decimal("10.00")), posicao_linha=1)
        assert item.tipo == tipo

    def test_e_estorno_apenas_para_tipo_estorno(self):
        compra = CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("10")))
        estorno = CompraCartao(tipo=TipoItemFatura.ESTORNO, valor=Dinheiro(Decimal("10")))
        assert compra.e_estorno is False
        assert estorno.e_estorno is True

    def test_metadado_parcelamento_nao_gera_lancamento_adicional(self):
        """D12 — parcela é metadado; CompraCartao carrega só o valor total."""
        item = CompraCartao(
            tipo=TipoItemFatura.COMPRA,
            valor=Dinheiro(Decimal("1200.00")),
            parcela_atual=1,
            total_parcelas=12,
        )
        # O valor lançado é o total da compra, não 1/12 dele.
        assert item.valor.valor == Decimal("1200.00")


# =============================================================
# FaturaCartao — D3, D5, D13, B2
# =============================================================

class TestFaturaCartaoFechamento:
    def _fatura(self, valor_total: str) -> FaturaCartao:
        return FaturaCartao(
            periodo_referencia=date(2026, 8, 1),
            valor_total_declarado=Dinheiro(Decimal(valor_total)),
        )

    def test_fechamento_exato(self):
        f = self._fatura("150.00")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.validar_fechamento()
        assert f.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_fechamento_com_encargos(self):
        """itens + encargos = total (D5, fórmula corrigida)."""
        f = self._fatura("160.00")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.itens.append(CompraCartao(tipo=TipoItemFatura.IOF, valor=Dinheiro(Decimal("10.00")), posicao_linha=2))
        f.validar_fechamento()
        assert f.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_fechamento_com_creditos_estorno(self):
        """itens - créditos/estornos = total (D5, fórmula corrigida)."""
        f = self._fatura("130.00")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.itens.append(CompraCartao(tipo=TipoItemFatura.ESTORNO, valor=Dinheiro(Decimal("20.00")), posicao_linha=2))
        f.validar_fechamento()
        assert f.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_divergencia_dentro_da_tolerancia(self):
        """Diferença de R$0,03, dentro da tolerância de R$0,05 (B2)."""
        f = self._fatura("150.03")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.validar_fechamento()
        assert f.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_divergencia_fora_da_tolerancia(self):
        """Diferença de R$0,10, fora da tolerância de R$0,05 (B2) — vai para revisão."""
        f = self._fatura("150.10")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.validar_fechamento()
        assert f.status_fechamento == StatusFechamentoFatura.DIVERGENTE

    def test_divergencia_nao_levanta_excecao(self):
        """Regra determinística com fallback de revisão, não bloqueio duro."""
        f = self._fatura("999.00")
        f.itens.append(CompraCartao(tipo=TipoItemFatura.COMPRA, valor=Dinheiro(Decimal("150.00")), posicao_linha=1))
        f.validar_fechamento()  # não deve levantar
        assert f.status_fechamento == StatusFechamentoFatura.DIVERGENTE

    def test_fatura_sem_itens_e_erro_de_uso(self):
        f = self._fatura("150.00")
        with pytest.raises(ValueError):
            f.validar_fechamento()

    def test_status_inicial_pendente(self):
        f = self._fatura("150.00")
        assert f.status_fechamento == StatusFechamentoFatura.PENDENTE


class TestFaturaCartaoIdempotencia:
    def test_chave_idempotencia_por_cartao_e_periodo(self):
        """D13 — chave de idempotência ao nível de fatura: (cartão, período)."""
        cartao_id = CartaoCredito(emissor="Nubank", final_numero="1234", titular="Camilo").id
        f1 = FaturaCartao(cartao_id=cartao_id, periodo_referencia=date(2026, 8, 1))
        f2 = FaturaCartao(cartao_id=cartao_id, periodo_referencia=date(2026, 8, 1))
        f3 = FaturaCartao(cartao_id=cartao_id, periodo_referencia=date(2026, 9, 1))

        assert f1.chave_idempotencia() == f2.chave_idempotencia()
        assert f1.chave_idempotencia() != f3.chave_idempotencia()
