"""Testes do parser de fatura de cartão — ADR 010, Fase 2.

AVISO DE EVIDÊNCIA (mesmo do módulo testado): os textos usados aqui são
SINTÉTICOS, escritos para exercitar o parser — NÃO são texto extraído
de uma fatura real (nenhum exemplo real está disponível no
repositório). Ver core/parsers/pdf/fatura_cartao_nubank.py, AVISO DE
EVIDÊNCIA, para o registro completo dessa limitação.
"""

from datetime import date
from decimal import Decimal

from core.domain.entities import ConfidenceScore, TipoItemFatura
from core.parsers.pdf.fatura_cartao_nubank import (
    CONFIANCA_PADRAO_TEXTO,
    CONFIANCA_SEM_CORRESPONDENCIA,
    classificar_tipo_item,
    extrair_itens,
    extrair_periodo_referencia,
    extrair_total_declarado,
    extrair_vencimento,
    parsear_fatura_texto,
)

# Texto sintético representativo — NÃO validado contra fatura real.
_TEXTO_FATURA_SINTETICA = """\
Fatura de Cartão de Crédito
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
06/08 IFOOD DELIVERY R$ 48,50
07/08 MAGAZINE LUIZA 3/12 R$ 100,00
10/08 IOF OPERACAO EXTERIOR R$ 4,32
12/08 JUROS ROTATIVO R$ 15,00
Total desta fatura R$ 193,72
"""


class TestExtrairVencimento:
    def test_extrai_vencimento_valido(self):
        assert extrair_vencimento(_TEXTO_FATURA_SINTETICA) == date(2026, 9, 15)

    def test_ausencia_de_vencimento_retorna_none(self):
        assert extrair_vencimento("texto sem nenhum campo de fatura") is None


class TestExtrairTotalDeclarado:
    def test_extrai_total_valido(self):
        assert extrair_total_declarado(_TEXTO_FATURA_SINTETICA) == Decimal("193.72")

    def test_ausencia_de_total_retorna_none(self):
        assert extrair_total_declarado("texto sem nenhum campo de fatura") is None


class TestExtrairPeriodoReferencia:
    def test_infere_periodo_do_mes_anterior_ao_vencimento(self):
        """Sem 'Fatura de MES/ANO' explícito, infere mês anterior ao vencimento."""
        periodo = extrair_periodo_referencia(
            "texto sem período explícito", vencimento=date(2026, 9, 15)
        )
        assert periodo == date(2026, 8, 1)

    def test_infere_periodo_com_virada_de_ano(self):
        periodo = extrair_periodo_referencia("texto qualquer", vencimento=date(2026, 1, 10))
        assert periodo == date(2025, 12, 1)

    def test_usa_periodo_explicito_quando_presente(self):
        texto = "Fatura de AGOSTO/2026\nOutros dados"
        periodo = extrair_periodo_referencia(texto, vencimento=date(2026, 9, 15))
        assert periodo == date(2026, 8, 1)

    def test_sem_vencimento_e_sem_periodo_explicito_retorna_none(self):
        assert extrair_periodo_referencia("texto qualquer", vencimento=None) is None


class TestClassificarTipoItem:
    def test_iof_reconhecido_por_palavra_chave(self):
        tipo, confidence = classificar_tipo_item("IOF OPERACAO EXTERIOR")
        assert tipo == TipoItemFatura.IOF
        assert confidence == CONFIANCA_PADRAO_TEXTO

    def test_juros_reconhecido_por_palavra_chave(self):
        tipo, _ = classificar_tipo_item("JUROS ROTATIVO")
        assert tipo == TipoItemFatura.JUROS

    def test_multa_reconhecida_por_palavra_chave(self):
        tipo, _ = classificar_tipo_item("MULTA POR ATRASO")
        assert tipo == TipoItemFatura.MULTA

    def test_anuidade_reconhecida_por_palavra_chave(self):
        tipo, _ = classificar_tipo_item("ANUIDADE CARTAO")
        assert tipo == TipoItemFatura.ANUIDADE

    def test_estorno_reconhecido_por_palavra_chave(self):
        tipo, _ = classificar_tipo_item("ESTORNO COMPRA CANCELADA")
        assert tipo == TipoItemFatura.ESTORNO

    def test_sem_correspondencia_classifica_como_compra_confianca_baixa(self):
        """B3 — sem correspondência clara, COMPRA com confiança abaixo do
        limiar de confiável (ConfidenceScore.e_confiavel = 0.90) — força
        revisão humana, não aceita silenciosamente."""
        tipo, confidence = classificar_tipo_item("UBER TRIP")
        assert tipo == TipoItemFatura.COMPRA
        assert confidence == CONFIANCA_SEM_CORRESPONDENCIA

    def test_toda_confianca_esta_abaixo_do_limiar_confiavel(self):
        """Nenhuma classificação desta primeira versão (não validada
        contra fatura real) deve ser tratada como 'confiável o
        suficiente' sem revisão — ver AVISO DE EVIDÊNCIA do módulo."""
        assert not ConfidenceScore(CONFIANCA_PADRAO_TEXTO, "tipo").e_confiavel
        assert not ConfidenceScore(CONFIANCA_SEM_CORRESPONDENCIA, "tipo").e_confiavel


class TestExtrairItens:
    def test_extrai_todos_os_itens_da_fatura_sintetica(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        assert len(itens) == 5

    def test_valores_extraidos_corretamente(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        valores = {item.estabelecimento: item.valor for item in itens}
        assert valores["UBER TRIP"] == Decimal("25.90")
        assert valores["IFOOD DELIVERY"] == Decimal("48.50")

    def test_parcela_extraida_do_texto(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        item_parcelado = next(i for i in itens if "MAGAZINE" in i.estabelecimento)
        assert item_parcelado.parcela_atual == 3
        assert item_parcelado.total_parcelas == 12

    def test_item_sem_parcela_tem_campos_none(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        item_simples = next(i for i in itens if i.estabelecimento == "UBER TRIP")
        assert item_simples.parcela_atual is None
        assert item_simples.total_parcelas is None

    def test_posicao_linha_sequencial(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        posicoes = [item.posicao_linha for item in itens]
        assert posicoes == sorted(posicoes)

    def test_linhas_sem_padrao_de_item_sao_ignoradas(self):
        """Cabeçalho ('Fatura de Cartão...', 'Vencimento:...') não vira item."""
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        descricoes = [i.estabelecimento for i in itens]
        assert "Fatura de Cartão de Crédito" not in descricoes

    def test_texto_sem_nenhum_item_retorna_lista_vazia(self):
        assert extrair_itens("texto qualquer sem formato de item") == []

    def test_tipo_iof_extraido_corretamente_do_item(self):
        itens = extrair_itens(_TEXTO_FATURA_SINTETICA)
        item_iof = next(i for i in itens if i.tipo == TipoItemFatura.IOF)
        assert "IOF" in item_iof.estabelecimento.upper()


class TestParsearFaturaTexto:
    def test_fluxo_completo_fatura_sintetica(self):
        resultado = parsear_fatura_texto(_TEXTO_FATURA_SINTETICA)
        assert resultado.data_vencimento == date(2026, 9, 15)
        assert resultado.valor_total_declarado == Decimal("193.72")
        assert resultado.periodo_referencia == date(2026, 8, 1)
        assert len(resultado.itens) == 5

    def test_texto_sem_campos_de_fatura_retorna_cabecalho_vazio(self):
        resultado = parsear_fatura_texto("texto qualquer, não é uma fatura")
        assert resultado.data_vencimento is None
        assert resultado.valor_total_declarado is None
        assert resultado.confidence_cabecalho == CONFIANCA_SEM_CORRESPONDENCIA

    def test_soma_dos_itens_bate_com_total_declarado(self):
        """Verificação de consistência do texto sintético em si — não é
        validação de fatura real, apenas garante que a fixture de teste
        está internamente coerente com D5."""
        resultado = parsear_fatura_texto(_TEXTO_FATURA_SINTETICA)
        soma = sum((item.valor for item in resultado.itens), Decimal("0"))
        assert soma == resultado.valor_total_declarado
