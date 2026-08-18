"""Testes dedicados de FITID — MotorConciliacao (Fase 5, ADR 010, D14).

Independentes da feature de cartão, conforme exigido na Deliberação
Complementar (B4) e reforçado no Gate B4-B: demonstram o caminho
`FITID -> Lancamento -> MotorConciliacao` funcionando de ponta a ponta,
a retrocompatibilidade da API anterior, e o comportamento correto para
lançamentos de cartão (nunca promovidos à Camada 1).

Herméticos: sem banco, arquivo ou rede — fitids_por_lancamento é
construído diretamente em memória pelos testes, simulando o que
core/cli.py::conciliacao_executar monta a partir de UnitOfWork.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

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
from core.rule_engine.motor_conciliacao import MotorConciliacao

EMPRESA_ID = uuid4()


def _conta() -> ContaBancaria:
    return ContaBancaria(instituicao="341", agencia="0001", numero_conta="12345-6")


def _tx(fitid: str = "TX001", valor: str = "100.00", data: date = date(2026, 7, 15)) -> TransacaoBancaria:
    return TransacaoBancaria(
        empresa_id=EMPRESA_ID,
        conta_bancaria=_conta(),
        fitid=fitid,
        data=data,
        valor=Dinheiro(Decimal(valor)),
        natureza=NaturezaLancamento.DEBITO,
        descricao="LOJA QUALQUER",
    )


def _lanc(
    valor: str = "100.00",
    data: date = date(2026, 7, 15),
    documento_id=None,
) -> Lancamento:
    """Lançamento genérico. documento_id=None simula um lançamento de
    cartão de crédito (D7/D8) — nunca tem Documento de origem."""
    return Lancamento(
        empresa_id=EMPRESA_ID,
        documento_id=documento_id,
        descricao="Lançamento de teste",
        status=StatusLancamento.APROVADO,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=data,
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO, valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO, valor=Dinheiro(Decimal(valor))),
        ],
    )


# =============================================================
# CENÁRIO 1 — Lançamento OFX + FITID correspondente → Camada 1
# =============================================================

class TestMatchExatoPorFitid:
    def test_lancamento_com_fitid_correspondente_concilia_por_fitid(self):
        """Evidência do match FITID: valor/data propositalmente NÃO
        bateriam sozinhos (diferença grande), mas o FITID força o match
        exato mesmo assim — prova de que é a Camada 1 decidindo, não a 2."""
        documento_id = uuid4()
        lanc = _lanc(valor="100.00", data=date(2026, 7, 15), documento_id=documento_id)
        tx = _tx(fitid="OFX-FITID-XYZ", valor="999.00", data=date(2026, 1, 1))  # bem diferente

        fitids = {lanc.id: "OFX-FITID-XYZ"}

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento=fitids,
        )

        item = relatorio.itens[0]
        assert item.status == TipoConciliacao.CONCILIADO
        assert item.metodo == MetodoMatching.FITID
        assert item.score == 1.0
        assert item.lancamento_id == lanc.id

    def test_fitid_tem_prioridade_sobre_candidato_por_valor_data(self):
        """Dois lançamentos candidatos por valor+data; só um tem FITID
        correspondente — o motor deve escolher o do FITID, não o outro."""
        documento_id = uuid4()
        lanc_fitid = _lanc(valor="50.00", data=date(2026, 7, 10), documento_id=documento_id)
        lanc_generico = _lanc(valor="50.00", data=date(2026, 7, 10))  # mesmo valor/data, sem FITID
        tx = _tx(fitid="FITID-CERTO", valor="50.00", data=date(2026, 7, 10))

        fitids = {lanc_fitid.id: "FITID-CERTO"}

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc_generico, lanc_fitid], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento=fitids,
        )

        item = relatorio.itens[0]
        assert item.metodo == MetodoMatching.FITID
        assert item.lancamento_id == lanc_fitid.id


# =============================================================
# CENÁRIO 2 — Lançamento sem FITID disponível → prossegue Camada 2
# =============================================================

class TestFallbackParaCamada2:
    def test_lancamento_sem_entrada_no_mapa_usa_valor_data(self):
        """Evidência do fallback: fitids_por_lancamento fornecido, mas
        vazio para este lançamento (ex.: Documento sem numero_documento)
        — motor cai para Camada 2 normalmente."""
        lanc = _lanc(valor="75.00", data=date(2026, 7, 20), documento_id=uuid4())
        tx = _tx(fitid="ALGUM-FITID-NAO-USADO", valor="75.00", data=date(2026, 7, 20))

        fitids: dict = {}  # mapa vazio — nenhuma entrada para este lançamento

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento=fitids,
        )

        item = relatorio.itens[0]
        assert item.status == TipoConciliacao.CONCILIADO
        assert item.metodo == MetodoMatching.VALOR_DATA  # não FITID

    def test_fitids_por_lancamento_none_equivale_a_mapa_vazio(self):
        """Passar None explicitamente (não apenas omitir) também deve
        cair em Camada 2 sem erro."""
        lanc = _lanc(valor="30.00", data=date(2026, 7, 5))
        tx = _tx(fitid="X", valor="30.00", data=date(2026, 7, 5))

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento=None,
        )

        item = relatorio.itens[0]
        assert item.metodo == MetodoMatching.VALOR_DATA


# =============================================================
# CENÁRIO 3 — Pagamento de cartão nunca promovido à Camada 1
# =============================================================

class TestCartaoNuncaPromovidoAFitid:
    def test_lancamento_sem_documento_id_nao_pode_ser_promovido_a_fitid(self):
        """Lançamento de cartão (documento_id=None, como D7/D8 geram)
        mesmo que, por engano do chamador, apareça em
        fitids_por_lancamento, representa um cenário que não deveria
        ocorrer na prática — mas o teste central é o caso real: o
        chamador (CLI) NUNCA inclui esses lançamentos no mapa, porque
        não tem documento_id para resolver. Aqui simulamos o caso real:
        ausência no mapa -> nunca casa por FITID."""
        lanc_cartao = _lanc(valor="200.00", data=date(2026, 7, 12), documento_id=None)
        tx = _tx(fitid="FITID-BANCO-PAGAMENTO-FATURA", valor="200.00", data=date(2026, 7, 12))

        # O chamador real (conciliacao_executar) pula lançamentos com
        # documento_id=None ao montar o mapa — reproduzido aqui:
        fitids: dict = {}

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc_cartao], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento=fitids,
        )

        item = relatorio.itens[0]
        assert item.metodo != MetodoMatching.FITID
        assert item.metodo == MetodoMatching.VALOR_DATA
        assert item.status == TipoConciliacao.CONCILIADO  # concilia, mas por Camada 2

    def test_lancamento_sem_documento_id_nunca_atinge_score_1_por_engano(self):
        """Reforço: mesmo com valor e data idênticos (o que já daria
        score alto), a ausência de FITID nunca eleva o score a 1.0 —
        1.0 é reservado exclusivamente ao método FITID."""
        lanc_cartao = _lanc(valor="200.00", data=date(2026, 7, 12), documento_id=None)
        tx = _tx(fitid="QUALQUER", valor="200.00", data=date(2026, 7, 12))

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc_cartao], transacoes=[tx], empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1), periodo_fim=date(2026, 12, 31),
            fitids_por_lancamento={},
        )

        item = relatorio.itens[0]
        assert item.score < 1.0


# =============================================================
# RETROCOMPATIBILIDADE — API anterior continua válida
# =============================================================

class TestRetrocompatibilidade:
    def test_conciliar_sem_o_novo_argumento_continua_funcionando(self):
        """Chamada EXATAMENTE como antes da Fase 5 — sem
        fitids_por_lancamento — deve continuar funcionando sem erro,
        com o mesmo comportamento de antes (Camada 1 nunca ativa)."""
        lanc = _lanc(valor="60.00", data=date(2026, 7, 8))
        tx = _tx(fitid="X", valor="60.00", data=date(2026, 7, 8))

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc],
            transacoes=[tx],
            empresa_id=EMPRESA_ID,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 12, 31),
        )  # sem fitids_por_lancamento — API antiga

        item = relatorio.itens[0]
        assert item.status == TipoConciliacao.CONCILIADO
        assert item.metodo == MetodoMatching.VALOR_DATA
