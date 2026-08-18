"""Testes de LancamentoService — Cartão de Crédito (ADR 010, Fase 3).

Cobre D7 (compra), D8 (pagamento agregado), D9 (IOF), D10 (juros/multa/
encargo), D11 (estorno) e D12 (parcelamento como metadado), conforme a
tabela de critérios do Gate de Fase 3.

Distinção estrutural exigida pelo gate: CompraCartao gera lançamento de
AQUISIÇÃO (D Despesa/Ativo / C Cartão); pagamento de fatura gera
lançamento de LIQUIDAÇÃO (D Cartão / C Banco) — dois métodos distintos,
nenhum encaixado no comportamento de _gerar_splits/Sugestao.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from core.domain.entities import (
    CodigoConta,
    CompraCartao,
    ConfidenceScore,
    Dinheiro,
    FaturaCartao,
    NaturezaLancamento,
    TipoItemFatura,
)
from core.rule_engine.lancamento_service import LancamentoService

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTA_DESPESA_GENERICA = CodigoConta("4.1.01.001")
CONTA_DESPESA_FINANCEIRA_IOF = CodigoConta("4.2.01.001")
CONTA_DESPESA_FINANCEIRA_JUROS = CodigoConta("4.2.01.002")
CONTA_DESPESA_FINANCEIRA_MULTA = CodigoConta("4.2.01.003")
CONTA_DESPESA_FINANCEIRA_ENCARGO = CodigoConta("4.2.01.004")


def _compra(
    tipo: TipoItemFatura = TipoItemFatura.COMPRA,
    valor: str = "100.00",
    parcela_atual: int | None = None,
    total_parcelas: int | None = None,
) -> CompraCartao:
    return CompraCartao(
        empresa_id=uuid4(),
        tipo=tipo,
        estabelecimento="ESTABELECIMENTO TESTE",
        data_compra=date(2026, 8, 5),
        valor=Dinheiro(Decimal(valor)),
        parcela_atual=parcela_atual,
        total_parcelas=total_parcelas,
        confidence=ConfidenceScore(0.95, "tipo"),
    )


def _fatura(valor_total: str = "300.00", n_itens: int = 3) -> FaturaCartao:
    f = FaturaCartao(
        empresa_id=uuid4(),
        periodo_referencia=date(2026, 8, 1),
        data_vencimento=date(2026, 9, 15),
        valor_total_declarado=Dinheiro(Decimal(valor_total)),
    )
    for _ in range(n_itens):
        f.itens.append(_compra(valor=str(Decimal(valor_total) / n_itens)))
    return f


# =============================================================
# D7 — COMPRA: D Despesa/Ativo / C Passivo Cartão
# =============================================================

class TestD7LancamentoCompra:
    def test_debito_e_credito_corretos(self):
        svc = LancamentoService()
        compra = _compra(tipo=TipoItemFatura.COMPRA, valor="150.00")

        lanc = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )

        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        credito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.CREDITO)
        assert debito.conta == CONTA_DESPESA_GENERICA
        assert credito.conta == CONTA_CARTAO
        assert debito.valor.valor == Decimal("150.00")
        assert credito.valor.valor == Decimal("150.00")

    def test_um_lancamento_por_compra(self):
        """Cada CompraCartao gera exatamente 1 Lancamento, não uma lista."""
        svc = LancamentoService()
        compra = _compra()
        lanc = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        assert len(lanc.splits) == 2

    def test_equilibrio_debito_credito(self):
        """Critério obrigatório: todo lançamento satisfaz D = C."""
        svc = LancamentoService()
        compra = _compra(valor="87.33")
        lanc = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        lanc.validar()  # não deve levantar


# =============================================================
# D9 — IOF: lançamento separado, não incorporado à compra
# =============================================================

class TestD9IOF:
    def test_iof_gera_lancamento_proprio(self):
        svc = LancamentoService()
        iof = _compra(tipo=TipoItemFatura.IOF, valor="4.32")

        lanc = svc.construir_lancamento_compra_cartao(
            iof, conta_despesa=CONTA_DESPESA_FINANCEIRA_IOF, conta_cartao=CONTA_CARTAO
        )

        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        assert debito.conta == CONTA_DESPESA_FINANCEIRA_IOF
        assert debito.valor.valor == Decimal("4.32")
        assert lanc.categoria == "iof"

    def test_iof_nao_incorporado_ao_valor_de_uma_compra(self):
        """IOF e a compra de origem são CompraCartao distintas — cada
        uma gera seu próprio lançamento, nunca somadas em um só."""
        svc = LancamentoService()
        compra = _compra(tipo=TipoItemFatura.COMPRA, valor="100.00")
        iof = _compra(tipo=TipoItemFatura.IOF, valor="4.32")

        lanc_compra = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        lanc_iof = svc.construir_lancamento_compra_cartao(
            iof, conta_despesa=CONTA_DESPESA_FINANCEIRA_IOF, conta_cartao=CONTA_CARTAO
        )

        assert lanc_compra.valor_total.valor == Decimal("100.00")
        assert lanc_iof.valor_total.valor == Decimal("4.32")
        assert lanc_compra.id != lanc_iof.id


# =============================================================
# D10 — Juros/multa/encargo: lançamentos separados, segregados
# =============================================================

class TestD10JurosMultaEncargo:
    def test_juros_gera_lancamento_proprio(self):
        svc = LancamentoService()
        juros = _compra(tipo=TipoItemFatura.JUROS, valor="15.00")
        lanc = svc.construir_lancamento_compra_cartao(
            juros, conta_despesa=CONTA_DESPESA_FINANCEIRA_JUROS, conta_cartao=CONTA_CARTAO
        )
        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        assert debito.conta == CONTA_DESPESA_FINANCEIRA_JUROS
        assert lanc.categoria == "juros"

    def test_multa_gera_lancamento_proprio(self):
        svc = LancamentoService()
        multa = _compra(tipo=TipoItemFatura.MULTA, valor="8.00")
        lanc = svc.construir_lancamento_compra_cartao(
            multa, conta_despesa=CONTA_DESPESA_FINANCEIRA_MULTA, conta_cartao=CONTA_CARTAO
        )
        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        assert debito.conta == CONTA_DESPESA_FINANCEIRA_MULTA
        assert lanc.categoria == "multa"

    def test_encargo_gera_lancamento_proprio(self):
        svc = LancamentoService()
        encargo = _compra(tipo=TipoItemFatura.ENCARGO, valor="3.50")
        lanc = svc.construir_lancamento_compra_cartao(
            encargo, conta_despesa=CONTA_DESPESA_FINANCEIRA_ENCARGO, conta_cartao=CONTA_CARTAO
        )
        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        assert debito.conta == CONTA_DESPESA_FINANCEIRA_ENCARGO
        assert lanc.categoria == "encargo"

    def test_juros_multa_encargo_em_contas_distintas_nao_genericas(self):
        """Segregação por natureza: cada tipo usa sua própria conta —
        nunca uma única conta genérica de 'despesa financeira'."""
        svc = LancamentoService()
        juros = svc.construir_lancamento_compra_cartao(
            _compra(tipo=TipoItemFatura.JUROS, valor="10"),
            conta_despesa=CONTA_DESPESA_FINANCEIRA_JUROS, conta_cartao=CONTA_CARTAO,
        )
        multa = svc.construir_lancamento_compra_cartao(
            _compra(tipo=TipoItemFatura.MULTA, valor="10"),
            conta_despesa=CONTA_DESPESA_FINANCEIRA_MULTA, conta_cartao=CONTA_CARTAO,
        )
        contas_debito = {
            next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO).conta
            for lanc in (juros, multa)
        }
        assert len(contas_debito) == 2  # nenhuma conta compartilhada

    def test_sem_sub_passivo_de_rotativo(self):
        """Nenhum tipo de encargo usa conta de passivo diferente de
        conta_cartao — não há sub-passivo de rotativo nesta fase."""
        svc = LancamentoService()
        for tipo, conta_despesa in (
            (TipoItemFatura.JUROS, CONTA_DESPESA_FINANCEIRA_JUROS),
            (TipoItemFatura.MULTA, CONTA_DESPESA_FINANCEIRA_MULTA),
            (TipoItemFatura.ENCARGO, CONTA_DESPESA_FINANCEIRA_ENCARGO),
        ):
            lanc = svc.construir_lancamento_compra_cartao(
                _compra(tipo=tipo, valor="10"),
                conta_despesa=conta_despesa, conta_cartao=CONTA_CARTAO,
            )
            credito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.CREDITO)
            assert credito.conta == CONTA_CARTAO  # sempre o mesmo passivo


# =============================================================
# D11 — Estorno: inversão correta
# =============================================================

class TestD11Estorno:
    def test_estorno_inverte_debito_e_credito(self):
        svc = LancamentoService()
        estorno = _compra(tipo=TipoItemFatura.ESTORNO, valor="20.00")

        lanc = svc.construir_lancamento_compra_cartao(
            estorno, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )

        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        credito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.CREDITO)
        # Invertido em relação a uma compra normal:
        assert debito.conta == CONTA_CARTAO
        assert credito.conta == CONTA_DESPESA_GENERICA

    def test_estorno_ainda_equilibrado(self):
        svc = LancamentoService()
        estorno = _compra(tipo=TipoItemFatura.ESTORNO, valor="20.00")
        lanc = svc.construir_lancamento_compra_cartao(
            estorno, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        lanc.validar()  # não deve levantar


# =============================================================
# D12 — Parcelamento: 1 lançamento pelo valor total, metadado apenas
# =============================================================

class TestD12Parcelamento:
    def test_compra_parcelada_gera_um_unico_lancamento_valor_total(self):
        svc = LancamentoService()
        compra = _compra(valor="1200.00", parcela_atual=3, total_parcelas=12)

        lanc = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )

        assert lanc.valor_total.valor == Decimal("1200.00")  # total, não 1/12
        assert lanc.e_parcelado is True
        assert lanc.parcela_atual == 3
        assert lanc.total_parcelas == 12

    def test_compra_nao_parcelada_e_parcelado_false(self):
        svc = LancamentoService()
        compra = _compra(valor="50.00")
        lanc = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        assert lanc.e_parcelado is False
        assert lanc.parcela_atual is None
        assert lanc.total_parcelas is None


# =============================================================
# D8 — PAGAMENTO: D Passivo Cartão / C Banco, agregado
# =============================================================

class TestD8LancamentoPagamento:
    def test_debito_e_credito_corretos(self):
        svc = LancamentoService()
        fatura = _fatura(valor_total="300.00", n_itens=3)

        lanc = svc.construir_lancamento_pagamento_fatura(
            fatura, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )

        debito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.DEBITO)
        credito = next(s for s in lanc.splits if s.natureza == NaturezaLancamento.CREDITO)
        assert debito.conta == CONTA_CARTAO
        assert credito.conta == CONTA_BANCO
        assert debito.valor.valor == Decimal("300.00")

    def test_um_unico_lancamento_agregado(self):
        """1 fatura com N itens -> 1 único Lancamento de pagamento."""
        svc = LancamentoService()
        fatura = _fatura(valor_total="450.00", n_itens=7)

        lanc = svc.construir_lancamento_pagamento_fatura(
            fatura, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )

        assert lanc.valor_total.valor == Decimal("450.00")
        assert len(lanc.splits) == 2  # sempre 2, independente de len(fatura.itens)

    def test_equilibrio_debito_credito(self):
        svc = LancamentoService()
        fatura = _fatura(valor_total="123.45", n_itens=2)
        lanc = svc.construir_lancamento_pagamento_fatura(
            fatura, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )
        lanc.validar()  # não deve levantar

    def test_valor_independe_do_numero_de_itens(self):
        """O valor do pagamento é sempre valor_total_declarado — nunca
        recalculado a partir da soma dos itens dentro deste método."""
        svc = LancamentoService()
        fatura_2_itens = _fatura(valor_total="500.00", n_itens=2)
        fatura_20_itens = _fatura(valor_total="500.00", n_itens=20)

        lanc_2 = svc.construir_lancamento_pagamento_fatura(
            fatura_2_itens, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )
        lanc_20 = svc.construir_lancamento_pagamento_fatura(
            fatura_20_itens, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )

        assert lanc_2.valor_total.valor == lanc_20.valor_total.valor == Decimal("500.00")


# =============================================================
# TESTE NEGATIVO OBRIGATÓRIO — nunca 1 lançamento de pagamento por compra
# =============================================================

class TestNegativoPagamentoNuncaPorCompra:
    def test_construir_lancamento_pagamento_fatura_nao_aceita_lista_de_compras(self):
        """A assinatura do método exige uma FaturaCartao, não uma lista
        de CompraCartao — não há caminho estrutural para gerar um
        lançamento de pagamento a partir de uma compra individual."""
        svc = LancamentoService()
        compra = _compra()

        with pytest.raises((TypeError, AttributeError)):
            # Passar uma CompraCartao onde se espera FaturaCartao deve
            # falhar, pois o método acessa atributos exclusivos de
            # FaturaCartao (valor_total_declarado, data_vencimento,
            # periodo_referencia) que CompraCartao não possui.
            svc.construir_lancamento_pagamento_fatura(
                compra, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
            )

    def test_numero_de_lancamentos_de_pagamento_gerados_e_sempre_um(self):
        """Gera lançamentos de compra para N itens (D7) e o lançamento
        de pagamento da fatura (D8) separadamente — confirma que o
        número de lançamentos de PAGAMENTO nunca escala com o número
        de itens da fatura."""
        svc = LancamentoService()
        fatura = _fatura(valor_total="300.00", n_itens=5)

        lancamentos_compra = [
            svc.construir_lancamento_compra_cartao(
                item, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
            )
            for item in fatura.itens
        ]
        lancamento_pagamento = svc.construir_lancamento_pagamento_fatura(
            fatura, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )

        assert len(lancamentos_compra) == 5  # 1 por CompraCartao (D7)
        assert isinstance(lancamento_pagamento, object)
        # lancamento_pagamento é um único objeto Lancamento, não uma
        # lista — não há como "1 por compra" ter sido gerado para pagamento.
        from core.domain.entities import Lancamento
        assert isinstance(lancamento_pagamento, Lancamento)
        assert not isinstance(lancamento_pagamento, list)


# =============================================================
# ISOLAMENTO DE FLUXO — compra e pagamento nunca se misturam
# =============================================================

class TestDistincaoAquisicaoLiquidacao:
    def test_lancamento_de_compra_e_de_pagamento_sao_objetos_distintos(self):
        svc = LancamentoService()
        fatura = _fatura(valor_total="100.00", n_itens=1)
        compra = fatura.itens[0]

        lanc_compra = svc.construir_lancamento_compra_cartao(
            compra, conta_despesa=CONTA_DESPESA_GENERICA, conta_cartao=CONTA_CARTAO
        )
        lanc_pagamento = svc.construir_lancamento_pagamento_fatura(
            fatura, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO
        )

        assert lanc_compra.id != lanc_pagamento.id
        # Compra: D despesa / C cartão. Pagamento: D cartão / C banco.
        debito_compra = next(s for s in lanc_compra.splits if s.natureza == NaturezaLancamento.DEBITO)
        debito_pagamento = next(s for s in lanc_pagamento.splits if s.natureza == NaturezaLancamento.DEBITO)
        assert debito_compra.conta == CONTA_DESPESA_GENERICA
        assert debito_pagamento.conta == CONTA_CARTAO
        assert debito_compra.conta != debito_pagamento.conta
