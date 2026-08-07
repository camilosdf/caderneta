"""Testes do LancamentoService — Motor Contábil.

Cobre: construção de splits, validação de balanço, período contábil,
centro de custo obrigatório, contas sintéticas, fluxo combinado processar().
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from core.domain.entities import (
    CentroCusto,
    CodigoConta,
    ContaContabil,
    Dinheiro,
    Documento,
    FonteExtracao,
    NaturezaLancamento,
    PeriodoContabil,
    StatusPeriodo,
    TipoDocumento,
)
from core.ports.classification import Sugestao
from core.rule_engine.lancamento_service import (
    CentroCustoObrigatorioError,
    ContaNaoLancavelError,
    LancamentoService,
)


# =============================================================
# HELPERS
# =============================================================

def _doc(valor: str = "100.00", data: date = date(2024, 3, 15)) -> Documento:
    return Documento(
        empresa_id=uuid4(),
        hash_sha256="a" * 64,
        nome_arquivo="teste.csv",
        tipo=TipoDocumento.CSV,
        fonte_extracao=FonteExtracao.CSV,
        data_emissao=data,
        valor_total=Dinheiro(Decimal(valor)),
        valor_liquido=Dinheiro(Decimal(valor)),
    )


def _sugestao(
    conta_debito="4.1.01.001",
    conta_credito="1.1.01.002",
    centro_custo=None,
    confidence=1.0,
) -> Sugestao:
    return Sugestao(
        categoria="Despesas Operacionais",
        conta_debito=CodigoConta(conta_debito) if conta_debito else None,
        conta_credito=CodigoConta(conta_credito) if conta_credito else None,
        centro_custo=centro_custo,
        confidence=confidence,
        metodo="regra_deterministica",
    )


# =============================================================
# CONSTRUÇÃO
# =============================================================

class TestConstruir:
    def test_gera_dois_splits(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao())
        assert len(lanc.splits) == 2

    def test_splits_naturezas_corretas(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao())
        naturezas = {s.natureza for s in lanc.splits}
        assert NaturezaLancamento.DEBITO in naturezas
        assert NaturezaLancamento.CREDITO in naturezas

    def test_valor_igual_ao_documento(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(valor="250.75"), _sugestao())
        for split in lanc.splits:
            assert split.valor.valor == Decimal("250.75")

    def test_sem_contas_gera_lancamento_sem_splits(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao(conta_debito=None, conta_credito=None))
        assert lanc.splits == []

    def test_descricao_do_documento(self) -> None:
        doc = _doc()
        doc.nome_emitente = "FORNECEDOR X"
        service = LancamentoService()
        lanc = service.construir(doc, _sugestao())
        assert lanc.descricao == "FORNECEDOR X"

    def test_sem_nome_emitente_usa_fallback(self) -> None:
        doc = _doc()
        doc.nome_emitente = None
        service = LancamentoService()
        lanc = service.construir(doc, _sugestao())
        assert lanc.descricao == "SEM DESCRIÇÃO"

    def test_categoria_confidence_metodo_propagados(self) -> None:
        service = LancamentoService()
        sug = _sugestao()
        lanc = service.construir(_doc(), sug)
        assert lanc.categoria == sug.categoria
        assert lanc.confidence == sug.confidence
        assert lanc.metodo_classificacao == sug.metodo

    def test_centro_custo_propagado_aos_splits(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao(centro_custo="CC-001"))
        assert all(s.centro_custo == "CC-001" for s in lanc.splits)

    def test_documento_sem_valor_usa_zero(self) -> None:
        doc = _doc()
        doc.valor_total = None
        doc.valor_liquido = None
        service = LancamentoService()
        lanc = service.construir(doc, _sugestao())
        assert lanc.splits[0].valor.valor == Decimal("0")


# =============================================================
# VALIDAÇÃO — BALANÇO
# =============================================================

class TestValidarBalanco:
    def test_lancamento_balanceado_nao_lanca_erro(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao())
        service.validar(lanc)  # não deve lançar

    def test_lancamento_sem_splits_lanca_erro(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(), _sugestao(conta_debito=None, conta_credito=None))
        with pytest.raises(ValueError, match="sem splits"):
            service.validar(lanc)


# =============================================================
# VALIDAÇÃO — PERÍODO CONTÁBIL
# =============================================================

class TestValidarPeriodo:
    def test_periodo_aberto_permite_lancamento(self) -> None:
        periodo = PeriodoContabil(ano=2024, mes=3, status=StatusPeriodo.ABERTO)
        service = LancamentoService(periodo_atual=periodo)
        lanc = service.construir(_doc(data=date(2024, 3, 15)), _sugestao())
        service.validar(lanc)  # não deve lançar

    def test_periodo_fechado_bloqueia_lancamento(self) -> None:
        periodo = PeriodoContabil(ano=2024, mes=3, status=StatusPeriodo.FECHADO)
        service = LancamentoService(periodo_atual=periodo)
        lanc = service.construir(_doc(data=date(2024, 3, 15)), _sugestao())
        with pytest.raises(ValueError, match="fechado"):
            service.validar(lanc)

    def test_periodo_diferente_da_data_nao_bloqueia(self) -> None:
        """Só valida se o período informado corresponde à competência do lançamento."""
        periodo = PeriodoContabil(ano=2024, mes=2, status=StatusPeriodo.FECHADO)
        service = LancamentoService(periodo_atual=periodo)
        lanc = service.construir(_doc(data=date(2024, 3, 15)), _sugestao())
        service.validar(lanc)  # não deve lançar — período fechado é de fevereiro, lançamento é de março

    def test_sem_periodo_configurado_nao_valida(self) -> None:
        service = LancamentoService()
        lanc = service.construir(_doc(data=date(2024, 3, 15)), _sugestao())
        service.validar(lanc)  # não deve lançar


# =============================================================
# VALIDAÇÃO — CONTAS E CENTRO DE CUSTO
# =============================================================

class TestValidarContasECentroCusto:
    def test_conta_sintetica_bloqueia_lancamento(self) -> None:
        conta_sintetica = ContaContabil(
            codigo=CodigoConta("4.1.01.001"),
            nome="Despesas Operacionais",
            permite_lancamento=True,
        )
        # Forçar sintética via código de 3 níveis
        conta_sintetica = ContaContabil(
            codigo=CodigoConta("4.1.01"),
            nome="Despesas",
        )
        contas = {"4.1.01.001": conta_sintetica}
        service = LancamentoService(contas_por_codigo=contas)
        # Sugestão usa código analítico mas o dict mapeia para conta sintética
        # (simula inconsistência de cadastro)
        lanc = service.construir(_doc(), _sugestao())
        with pytest.raises(ContaNaoLancavelError):
            service.validar(lanc)

    def test_conta_nao_lancavel_bloqueia(self) -> None:
        conta = ContaContabil(
            codigo=CodigoConta("4.1.01.001"),
            nome="Bloqueada",
            permite_lancamento=False,
        )
        contas = {"4.1.01.001": conta}
        service = LancamentoService(contas_por_codigo=contas)
        lanc = service.construir(_doc(), _sugestao())
        with pytest.raises(ContaNaoLancavelError):
            service.validar(lanc)

    def test_centro_custo_obrigatorio_sem_informar_bloqueia(self) -> None:
        conta = ContaContabil(
            codigo=CodigoConta("4.1.01.001"),
            nome="Requer CC",
            centro_custo_obrigatorio=True,
        )
        contas = {"4.1.01.001": conta}
        service = LancamentoService(contas_por_codigo=contas)
        lanc = service.construir(_doc(), _sugestao(centro_custo=None))
        with pytest.raises(CentroCustoObrigatorioError):
            service.validar(lanc)

    def test_centro_custo_obrigatorio_informado_passa(self) -> None:
        conta = ContaContabil(
            codigo=CodigoConta("4.1.01.001"),
            nome="Requer CC",
            centro_custo_obrigatorio=True,
        )
        contas = {"4.1.01.001": conta}
        service = LancamentoService(contas_por_codigo=contas)
        lanc = service.construir(_doc(), _sugestao(centro_custo="CC-001"))
        service.validar(lanc)  # não deve lançar

    def test_conta_nao_cadastrada_nao_bloqueia(self) -> None:
        """Contas fora do dict são ignoradas na validação (cadastro incompleto)."""
        service = LancamentoService(contas_por_codigo={})
        lanc = service.construir(_doc(), _sugestao())
        service.validar(lanc)  # não deve lançar

    def test_centro_custo_inativo_bloqueia(self) -> None:
        centro = CentroCusto(codigo="CC-001", nome="Inativo", ativo=False)
        centros = {"CC-001": centro}
        service = LancamentoService(centros_por_codigo=centros)
        lanc = service.construir(_doc(), _sugestao(centro_custo="CC-001"))
        with pytest.raises(ValueError, match="inativo"):
            service.validar(lanc)

    def test_centro_custo_ativo_passa(self) -> None:
        centro = CentroCusto(codigo="CC-001", nome="Ativo", ativo=True)
        centros = {"CC-001": centro}
        service = LancamentoService(centros_por_codigo=centros)
        lanc = service.construir(_doc(), _sugestao(centro_custo="CC-001"))
        service.validar(lanc)  # não deve lançar


# =============================================================
# FLUXO COMBINADO — processar()
# =============================================================

class TestProcessar:
    def test_processar_constroi_e_valida(self) -> None:
        service = LancamentoService()
        lanc = service.processar(_doc(), _sugestao())
        assert len(lanc.splits) == 2

    def test_processar_sem_splits_nao_lanca_erro(self) -> None:
        """Sugestão sem contas retorna lançamento vazio, sem exceção —
        cabe ao chamador decidir (ex.: marcar para revisão)."""
        service = LancamentoService()
        sug_vazia = _sugestao(conta_debito=None, conta_credito=None)
        lanc = service.processar(_doc(), sug_vazia)
        assert lanc.splits == []

    def test_processar_propaga_erro_de_periodo_fechado(self) -> None:
        periodo = PeriodoContabil(ano=2024, mes=3, status=StatusPeriodo.FECHADO)
        service = LancamentoService(periodo_atual=periodo)
        with pytest.raises(ValueError, match="fechado"):
            service.processar(_doc(data=date(2024, 3, 15)), _sugestao())

    def test_processar_end_to_end_completo(self) -> None:
        """Cenário realista: contas cadastradas, centro de custo, período aberto."""
        conta_debito = ContaContabil(
            codigo=CodigoConta("4.1.01.001"), nome="Despesas Operacionais",
            centro_custo_obrigatorio=True,
        )
        conta_credito = ContaContabil(
            codigo=CodigoConta("1.1.01.002"), nome="Caixa",
        )
        centro = CentroCusto(codigo="CC-VENDAS", nome="Vendas", ativo=True)
        periodo = PeriodoContabil(ano=2024, mes=3, status=StatusPeriodo.ABERTO)

        service = LancamentoService(
            contas_por_codigo={
                "4.1.01.001": conta_debito,
                "1.1.01.002": conta_credito,
            },
            centros_por_codigo={"CC-VENDAS": centro},
            periodo_atual=periodo,
        )

        doc = _doc(valor="500.00", data=date(2024, 3, 20))
        sug = _sugestao(centro_custo="CC-VENDAS")

        lanc = service.processar(doc, sug)

        assert len(lanc.splits) == 2
        assert lanc.splits[0].valor.valor == Decimal("500.00")
        assert all(s.centro_custo == "CC-VENDAS" for s in lanc.splits)
