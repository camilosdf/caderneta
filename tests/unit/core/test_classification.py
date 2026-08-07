"""Testes do Rule Engine de Classificação — Etapa 3.

Cobre: RegrasDeterministicasPlugin, normalização de fornecedores.
Meta: elevar cobertura de core/rule_engine/classification_impl.py de 0% para ≥ 85%.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from core.domain.entities import (
    ConfidenceScore,
    Dinheiro,
    Documento,
    FonteExtracao,
    Fornecedor,
    NaturezaLancamento,
    TipoDocumento,
)
from core.ports.classification import ResultadoNormalizacao, Sugestao
from core.rule_engine.classification_impl import RegrasDeterministicasPlugin


# =============================================================
# HELPERS
# =============================================================

def _doc(descricao: str, valor: float = 50.0) -> Documento:
    return Documento(
        tipo=TipoDocumento.CSV,
        nome_arquivo="teste.csv",
        hash_sha256="abc123",
        nome_emitente=descricao,
        data_emissao=date(2026, 6, 1),
        valor_total=Dinheiro(Decimal(str(valor))),
        valor_liquido=Dinheiro(Decimal(str(valor))),
        fonte_extracao=FonteExtracao.CSV,
        confidence_scores=[ConfidenceScore(1.0, "valor")],
        natureza_operacao=NaturezaLancamento.DEBITO,
    )


def _regra(
    nome: str,
    termos: list[str],
    categoria: str,
    conta_debito: str = "4.1.01.001",
    conta_credito: str = "1.1.01.002",
    prioridade: int = 10,
) -> Any:
    from core.rule_engine.rule_entity import RegraClassificacaoV2
    from core.domain.entities import CodigoConta
    return RegraClassificacaoV2(
        nome=nome,
        condicao={"descricao_contains_any": termos},
        categoria=categoria,
        conta_debito=CodigoConta(conta_debito),
        conta_credito=CodigoConta(conta_credito),
        prioridade=prioridade,
        criada_por="teste",
    )


def _classificador(*regras) -> RegrasDeterministicasPlugin:
    return RegrasDeterministicasPlugin(regras=list(regras), fornecedores=[])


# =============================================================
# CLASSIFICAÇÃO POR REGRAS
# =============================================================

class TestClassificacaoRegras:
    def test_classifica_uber_como_transporte(self) -> None:
        clf = _classificador(_regra("Uber", ["UBER"], "Transporte"))
        resultado = clf.sugerir_categoria(_doc("UBER VIAGEM SP"), None)
        assert resultado.categoria == "Transporte"
        assert resultado.confidence == 1.0

    def test_classifica_supermercado_como_alimentacao(self) -> None:
        clf = _classificador(_regra("Supermercado", ["SUPERMERCADO", "MERCADO"], "Alimentação"))
        resultado = clf.sugerir_categoria(_doc("SUPERMERCADO EXTRA"), None)
        assert resultado.categoria == "Alimentação"

    def test_desconhecido_vai_para_revisao(self) -> None:
        clf = _classificador()
        resultado = clf.sugerir_categoria(_doc("FORNECEDOR XPTO DESCONHECIDO"), None)
        assert resultado.precisa_revisao is True
        assert resultado.confidence == 0.0

    def test_fallback_categoria_outras_despesas(self) -> None:
        clf = _classificador()
        resultado = clf.sugerir_categoria(_doc("SEM MATCH"), None)
        assert resultado.categoria == "Outras Despesas"

    def test_metodo_regra_deterministica(self) -> None:
        clf = _classificador(_regra("Farmácia", ["FARMACIA"], "Saúde"))
        resultado = clf.sugerir_categoria(_doc("FARMACIA PACHECO"), None)
        assert resultado.metodo == "regra_deterministica"

    def test_regra_inativa_nao_aplicada(self) -> None:
        regra = _regra("Inativa", ["UBER"], "Transporte")
        regra.ativa = False
        clf = _classificador(regra)
        resultado = clf.sugerir_categoria(_doc("UBER VIAGEM"), None)
        assert resultado.precisa_revisao is True  # nenhuma regra ativa aplicada

    def test_prioridade_menor_vence(self) -> None:
        """Regra com menor prioridade (número menor) deve ser aplicada primeiro."""
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        r1 = RegraClassificacaoV2(
            nome="Alta prioridade",
            condicao={"descricao_contains_any": ["AMAZON"]},
            categoria="SaaS",
            conta_debito=CodigoConta("4.1.01.006"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=5,
        )
        r2 = RegraClassificacaoV2(
            nome="Baixa prioridade",
            condicao={"descricao_contains_any": ["AMAZON"]},
            categoria="Compras",
            conta_debito=CodigoConta("4.1.01.099"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=50,
        )
        clf = RegrasDeterministicasPlugin(regras=[r1, r2], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc("AMAZON PRIME"), None)
        assert resultado.categoria == "SaaS"

    def test_match_case_insensitive(self) -> None:
        clf = _classificador(_regra("Ifood", ["IFOOD"], "Alimentação"))
        resultado = clf.sugerir_categoria(_doc("ifood delivery"), None)
        assert resultado.categoria == "Alimentação"

    def test_regra_com_cfop(self) -> None:
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        regra_cfop = RegraClassificacaoV2(
            nome="NF-e serviço",
            condicao={"cfop": "5933"},
            categoria="Serviços",
            conta_debito=CodigoConta("1.1.01.002"),
            conta_credito=CodigoConta("3.1.01.001"),
            prioridade=5,
        )
        clf = RegrasDeterministicasPlugin(regras=[regra_cfop], fornecedores=[])
        doc = _doc("NF-e SERVICO")
        doc.cfop = "5933"
        resultado = clf.sugerir_categoria(doc, None)
        assert resultado.categoria == "Serviços"

    def test_regra_com_tipo_lancamento_credito(self) -> None:
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        regra_pix = RegraClassificacaoV2(
            nome="PIX recebido",
            condicao={
                "descricao_contains_any": ["PIX RECEBIDO"],
                "tipo_lancamento": "credito",
            },
            categoria="Receitas",
            conta_debito=CodigoConta("1.1.01.002"),
            conta_credito=CodigoConta("3.2.01.001"),
            prioridade=1,
        )
        clf = RegrasDeterministicasPlugin(regras=[regra_pix], fornecedores=[])
        doc = _doc("PIX RECEBIDO JOAO")
        doc.natureza_operacao = NaturezaLancamento.CREDITO
        resultado = clf.sugerir_categoria(doc, None)
        assert resultado.categoria == "Receitas"


# =============================================================
# NORMALIZAÇÃO DE FORNECEDORES
# =============================================================

class TestNormalizacao:
    def _fornecedor(self, nome: str, aliases: list[str] = None) -> Fornecedor:
        return Fornecedor(
            nome_canonico=nome,
            aliases=aliases or [],
            categoria="teste",
        )

    def test_busca_exata(self) -> None:
        f = self._fornecedor("SUPERMERCADO BOM PREÇO")
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[f])
        resultado = clf.normalizar_fornecedor("SUPERMERCADO BOM PREÇO")
        assert resultado.confidence == 1.0
        assert resultado.metodo == "exato"
        assert resultado.fornecedor_id == f.id

    def test_busca_por_alias(self) -> None:
        f = self._fornecedor("SUPERMERCADO BOM PREÇO", ["SUP BOMPRECO", "BOM PRECO"])
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[f])
        resultado = clf.normalizar_fornecedor("SUP BOMPRECO")
        assert resultado.fornecedor_id == f.id
        assert resultado.metodo == "alias"

    def test_busca_por_prefixo(self) -> None:
        f = self._fornecedor("UBER")
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[f])
        resultado = clf.normalizar_fornecedor("UBER *TRIP 12345")
        assert resultado.fornecedor_id == f.id
        assert resultado.metodo == "prefixo"

    def test_novo_fornecedor_vai_para_revisao(self) -> None:
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[])
        resultado = clf.normalizar_fornecedor("LOJA TOTALMENTE NOVA 99999")
        assert resultado.precisa_revisao is True
        assert resultado.metodo == "novo"
        assert resultado.fornecedor_id is None

    def test_nome_vazio_vai_para_revisao(self) -> None:
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[])
        resultado = clf.normalizar_fornecedor("")
        assert resultado.precisa_revisao is True

    def test_remove_acentos_na_comparacao(self) -> None:
        f = self._fornecedor("PADARIA DO ZÉZINHO")
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[f])
        resultado = clf.normalizar_fornecedor("PADARIA DO ZEZINHO")
        assert resultado.fornecedor_id == f.id

    def test_remove_asterisco(self) -> None:
        """'AMAZON*PRIME' deve ser normalizado para 'AMAZON PRIME'."""
        f = self._fornecedor("AMAZON PRIME")
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[f])
        resultado = clf.normalizar_fornecedor("AMAZON*PRIME")
        assert resultado.fornecedor_id == f.id

    def test_satisfaz_classification_port(self) -> None:
        """RegrasDeterministicasPlugin deve satisfazer ClassificationPort."""
        from core.ports.classification import ClassificationPort
        clf = RegrasDeterministicasPlugin(regras=[], fornecedores=[])
        assert isinstance(clf, ClassificationPort)


# =============================================================
# CLASSIFICAÇÃO POR CONDIÇÕES NF-e
# =============================================================

def _doc_nfe(
    cfop_itens: tuple = ("5102",),
    ncm_itens: tuple = ("84713012",),
    cst: str = "00",
    finalidade: int = 1,
    nat_op: str = "Venda",
) -> Documento:
    from core.domain.entities import (
        CNPJ, CodigoConta, Dinheiro, MetadadosNFe, TipoDocumento, FonteExtracao,
        NaturezaLancamento,
    )
    from decimal import Decimal

    meta = MetadadosNFe(
        chave_acesso="35240312345678000195550010000000011000000011",
        finalidade=finalidade,
        natureza_operacao_texto=nat_op,
        cfop_itens=cfop_itens,
        ncm_itens=ncm_itens,
        cst_icms=cst,
        cnpj_destinatario=None,
        valor_icms=Dinheiro(Decimal("0")),
        valor_pis=Dinheiro(Decimal("0")),
        valor_cofins=Dinheiro(Decimal("0")),
        valor_ipi=Dinheiro(Decimal("0")),
    )
    return Documento(
        tipo=TipoDocumento.NFE_XML,
        nome_arquivo="nfe.xml",
        hash_sha256="abc",
        nome_emitente="FORNECEDOR NF-e",
        data_emissao=date(2024, 3, 15),
        valor_total=Dinheiro(Decimal("100.00")),
        valor_liquido=Dinheiro(Decimal("100.00")),
        fonte_extracao=FonteExtracao.XML,
        cfop="5102",
        natureza_operacao=NaturezaLancamento.CREDITO,
        metadados_nfe=meta,
        confidence_scores=[],
    )


def _regra_nfe(nome: str, condicao: dict, categoria: str) -> Any:
    from core.rule_engine.rule_entity import RegraClassificacaoV2
    from core.domain.entities import CodigoConta
    return RegraClassificacaoV2(
        nome=nome,
        condicao=condicao,
        categoria=categoria,
        conta_debito=CodigoConta("1.1.01.002"),
        conta_credito=CodigoConta("3.1.01.001"),
        prioridade=5,
        criada_por="teste",
    )


class TestClassificacaoNFe:
    def test_cfop_prefixo_venda_classifica(self) -> None:
        regra = _regra_nfe("Venda mercadoria", {"cfop_prefixo": "51"}, "Receita de Vendas")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(cfop_itens=("5102",)), None)
        assert resultado.categoria == "Receita de Vendas"

    def test_cfop_prefixo_nao_bate(self) -> None:
        regra = _regra_nfe("Venda mercadoria", {"cfop_prefixo": "51"}, "Receita de Vendas")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(cfop_itens=("1102",)), None)
        assert resultado.precisa_revisao is True

    def test_cfop_prefixo_sem_metadados_nao_bate(self) -> None:
        regra = _regra_nfe("Venda", {"cfop_prefixo": "51"}, "Receita de Vendas")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        doc = _doc("QUALQUER DOC SEM NFE")
        resultado = clf.sugerir_categoria(doc, None)
        assert resultado.precisa_revisao is True

    def test_ncm_contains_any_bate(self) -> None:
        regra = _regra_nfe("TI", {"ncm_contains_any": ["8471"]}, "Ativo de TI")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(ncm_itens=("84713012",)), None)
        assert resultado.categoria == "Ativo de TI"

    def test_ncm_contains_any_nao_bate(self) -> None:
        regra = _regra_nfe("TI", {"ncm_contains_any": ["8471"]}, "Ativo de TI")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(ncm_itens=("39269090",)), None)
        assert resultado.precisa_revisao is True

    def test_cst_icms_bate(self) -> None:
        regra = _regra_nfe("Isento", {"cst_icms": "40"}, "Compra Isenta ICMS")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(cst="40"), None)
        assert resultado.categoria == "Compra Isenta ICMS"

    def test_cst_icms_nao_bate(self) -> None:
        regra = _regra_nfe("Isento", {"cst_icms": "40"}, "Compra Isenta ICMS")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(cst="00"), None)
        assert resultado.precisa_revisao is True

    def test_e_devolucao_true_bate(self) -> None:
        regra = _regra_nfe("Devolução", {"e_devolucao": True}, "Devolução de Venda")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(finalidade=4), None)
        assert resultado.categoria == "Devolução de Venda"

    def test_e_devolucao_false_nao_bate(self) -> None:
        regra = _regra_nfe("Devolução", {"e_devolucao": True}, "Devolução de Venda")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(_doc_nfe(finalidade=1), None)
        assert resultado.precisa_revisao is True

    def test_combinacao_cfop_e_ncm(self) -> None:
        """CFOP 51xx + NCM 8471 = Venda de equipamento de TI."""
        regra = _regra_nfe(
            "Venda TI",
            {"cfop_prefixo": "51", "ncm_contains_any": ["8471"]},
            "Receita Venda TI",
        )
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(
            _doc_nfe(cfop_itens=("5102",), ncm_itens=("84713012",)), None
        )
        assert resultado.categoria == "Receita Venda TI"

    def test_combinacao_cfop_e_ncm_falha_se_ncm_errado(self) -> None:
        regra = _regra_nfe(
            "Venda TI",
            {"cfop_prefixo": "51", "ncm_contains_any": ["8471"]},
            "Receita Venda TI",
        )
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(
            _doc_nfe(cfop_itens=("5102",), ncm_itens=("39269090",)), None
        )
        assert resultado.precisa_revisao is True

    def test_multiplos_ncm_um_bate(self) -> None:
        """Se qualquer NCM da NF-e bater no prefixo, a regra se aplica."""
        regra = _regra_nfe("TI", {"ncm_contains_any": ["8471"]}, "Ativo de TI")
        clf = RegrasDeterministicasPlugin(regras=[regra], fornecedores=[])
        resultado = clf.sugerir_categoria(
            _doc_nfe(ncm_itens=("39269090", "84713012")), None
        )
        assert resultado.categoria == "Ativo de TI"
