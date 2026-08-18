"""Parser de fatura de cartão de crédito em PDF — ADR 010, Fase 2.

Primeiro emissor suportado: Nubank — mesmo emissor já coberto pelo
parser CSV existente em core/parsers/csv/nubank.py (reaproveita a
convenção já estabelecida no projeto; ver Gate pré-Fase 2, item
"reaproveitar infraestrutura existente... sem criar funcionalidades de
outros emissores").

AVISO DE EVIDÊNCIA — B3 (Deliberação Complementar / Gate pré-Fase 2):
Não há, em tests/fixtures nem em qualquer outro lugar do repositório,
nenhum exemplo real de fatura de cartão em PDF. A extração de campos
de cabeçalho e de itens abaixo é construída a partir de convenções
genéricas e campos de divulgação obrigatória conhecidos do setor
bancário brasileiro — NÃO validada contra um layout real do emissor.

Por isso:
  - A confiança atribuída a TODO item extraído do texto é mantida
    deliberadamente abaixo do limiar ConfidenceScore.e_confiavel
    (0.90) — nenhum item cai em lançamento automático sem revisão
    humana até que o padrão seja validado contra faturas reais.
  - Este módulo não deve ser tratado como "B3 resolvido definitivamente"
    — é a melhor extração possível sem evidência real disponível,
    documentada como tal.

Se, ao processar uma fatura real, o padrão não corresponder ao layout
do emissor, a correção deve seguir a evidência (ajustar o padrão com
base no exemplo real), nunca ser forçada para "passar no teste".
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from core.domain.entities import TipoItemFatura

# ---------------------------------------------------------------------------
# Confiança — deliberadamente conservadora (ver AVISO DE EVIDÊNCIA acima).
# Ambos os valores ficam abaixo de ConfidenceScore.e_confiavel (0.90):
# nenhuma extração desta primeira versão é tratada como "confiável o
# suficiente para lançamento automático" sem revisão humana.
# ---------------------------------------------------------------------------
CONFIANCA_PADRAO_TEXTO = 0.80          # correspondência de padrão encontrada
CONFIANCA_SEM_CORRESPONDENCIA = 0.50   # nenhuma palavra-chave de tipo bateu

# Palavras-chave por tipo de item (B3 — Deliberação Complementar, Gate de
# Implementação ADR 010). Lista aberta, extensível conforme faturas reais
# forem processadas — não é uma lista exaustiva por emissor.
_PALAVRAS_CHAVE_TIPO: dict[TipoItemFatura, tuple[str, ...]] = {
    TipoItemFatura.IOF: ("IOF",),
    TipoItemFatura.JUROS: ("JUROS",),
    TipoItemFatura.MULTA: ("MULTA",),
    TipoItemFatura.ANUIDADE: ("ANUIDADE",),
    TipoItemFatura.ESTORNO: ("ESTORNO", "CREDITO", "CRÉDITO", "CANCELAMENTO"),
    TipoItemFatura.ENCARGO: ("ENCARGO", "TARIFA", "TAXA DE"),
}

_MESES_PT = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

_PADRAO_VENCIMENTO = re.compile(
    r"VENCIMENTO[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE
)
_PADRAO_TOTAL = re.compile(
    r"(?:TOTAL\s+DESTA\s+FATURA|VALOR\s+TOTAL\s+DA\s+FATURA|TOTAL\s+A\s+PAGAR)"
    r"[:\s]*R?\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_PADRAO_PERIODO_EXPLICITO = re.compile(
    r"FATURA\s+DE\s+([A-ZÇ]{3,})\s*/\s*(\d{4})", re.IGNORECASE
)
_PADRAO_ITEM = re.compile(
    r"^(?P<data>\d{2}/\d{2}(?:/\d{4})?)\s+"
    r"(?P<descricao>.+?)\s+"
    r"R?\$?\s*(?P<valor>-?[\d.]+,\d{2})\s*$"
)
_PADRAO_PARCELA = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")


@dataclass
class ItemExtraido:
    """Item de fatura extraído do texto, antes de virar CompraCartao."""
    descricao_original: str
    valor: Decimal
    tipo: TipoItemFatura
    confidence: float
    posicao_linha: int
    data_compra: date | None = None
    estabelecimento: str | None = None
    parcela_atual: int | None = None
    total_parcelas: int | None = None


@dataclass
class FaturaExtraida:
    """Resultado da extração estruturada de uma fatura (cabeçalho + itens)."""
    periodo_referencia: date | None = None
    data_vencimento: date | None = None
    valor_total_declarado: Decimal | None = None
    itens: list[ItemExtraido] = field(default_factory=list)
    confidence_cabecalho: float = CONFIANCA_SEM_CORRESPONDENCIA


def classificar_tipo_item(descricao: str) -> tuple[TipoItemFatura, float]:
    """Classifica o tipo de um item de fatura por palavra-chave (B3).

    Sem correspondência clara, classifica como COMPRA com confiança
    baixa (abaixo do limiar de confiável) — o item cai em revisão
    humana pelo mecanismo já existente (ConfidenceScore.e_confiavel),
    não é aceito silenciosamente como se fosse uma compra confirmada.
    """
    descricao_upper = descricao.upper()
    for tipo, palavras in _PALAVRAS_CHAVE_TIPO.items():
        if any(p in descricao_upper for p in palavras):
            return tipo, CONFIANCA_PADRAO_TEXTO
    return TipoItemFatura.COMPRA, CONFIANCA_SEM_CORRESPONDENCIA


def extrair_vencimento(texto: str) -> date | None:
    """Extrai a data de vencimento da fatura (campo de divulgação obrigatória)."""
    m = _PADRAO_VENCIMENTO.search(texto)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None


def extrair_total_declarado(texto: str) -> Decimal | None:
    """Extrai o valor total declarado da fatura (campo de divulgação obrigatória)."""
    m = _PADRAO_TOTAL.search(texto)
    if not m:
        return None
    valor_str = m.group(1).replace(".", "").replace(",", ".")
    try:
        return Decimal(valor_str)
    except InvalidOperation:
        return None


def extrair_periodo_referencia(texto: str, vencimento: date | None) -> date | None:
    """Período de referência da fatura (primeiro dia do mês de fechamento).

    Tenta primeiro um padrão explícito ("Fatura de AGOSTO/2026"). Sem
    correspondência, infere o período como o mês anterior ao
    vencimento — convenção comum no setor, mas NÃO validada contra
    fatura real (ver AVISO DE EVIDÊNCIA do módulo). A ausência de um
    padrão explícito não impede o processamento, mas o item de
    cabeçalho correspondente deve ser tratado como inferido, não como
    fato extraído diretamente.
    """
    m = _PADRAO_PERIODO_EXPLICITO.search(texto)
    if m:
        mes = _MESES_PT.get(m.group(1).upper()[:3])
        if mes:
            return date(int(m.group(2)), mes, 1)

    if vencimento is None:
        return None

    ano, mes = vencimento.year, vencimento.month - 1
    if mes == 0:
        mes, ano = 12, ano - 1
    return date(ano, mes, 1)


def extrair_itens(texto: str) -> list[ItemExtraido]:
    """Extrai itens de linha da fatura (compras, encargos, estornos).

    Cada linha que corresponde ao padrão data+descrição+valor vira um
    ItemExtraido. Linhas que não correspondem (cabeçalho, rodapé,
    texto solto) são ignoradas — não geram item nem erro.
    """
    itens: list[ItemExtraido] = []
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]

    for posicao, linha in enumerate(linhas, start=1):
        m = _PADRAO_ITEM.match(linha)
        if not m:
            continue

        descricao = m.group("descricao").strip()
        valor_str = m.group("valor").replace(".", "").replace(",", ".")
        try:
            valor = abs(Decimal(valor_str))
        except InvalidOperation:
            continue

        data_compra = None
        data_str = m.group("data")
        try:
            if len(data_str) == 5:  # DD/MM sem ano — assume ano corrente
                data_compra = datetime.strptime(
                    f"{data_str}/{datetime.now().year}", "%d/%m/%Y"
                ).date()
            else:
                data_compra = datetime.strptime(data_str, "%d/%m/%Y").date()
        except ValueError:
            data_compra = None

        tipo, confidence = classificar_tipo_item(descricao)

        parcela_atual = total_parcelas = None
        m_parcela = _PADRAO_PARCELA.search(descricao)
        if m_parcela:
            parcela_atual = int(m_parcela.group(1))
            total_parcelas = int(m_parcela.group(2))

        itens.append(ItemExtraido(
            descricao_original=linha,
            estabelecimento=descricao,
            valor=valor,
            tipo=tipo,
            confidence=confidence,
            posicao_linha=posicao,
            data_compra=data_compra,
            parcela_atual=parcela_atual,
            total_parcelas=total_parcelas,
        ))

    return itens


def parsear_fatura_texto(texto: str) -> FaturaExtraida:
    """Ponto de entrada único do parser: texto bruto -> FaturaExtraida.

    O texto pode vir de duas origens (Fase 2, Gate pré-Fase 2):
      - PDF_TEXTO: extração direta via pdfplumber
      - PDF_IMAGEM: OCRPlugin.extrair_de_arquivo()["texto_bruto"]

    Este parser não sabe nem precisa saber qual foi a origem — a
    diferença de confiabilidade entre os dois caminhos já está refletida
    na confiança que cada um propaga a montante (ver ai/ocr/ocr_plugin.py
    para o caminho OCR).
    """
    vencimento = extrair_vencimento(texto)
    total = extrair_total_declarado(texto)
    periodo = extrair_periodo_referencia(texto, vencimento)
    itens = extrair_itens(texto)

    confidence_cabecalho = (
        CONFIANCA_PADRAO_TEXTO
        if (vencimento is not None and total is not None)
        else CONFIANCA_SEM_CORRESPONDENCIA
    )

    return FaturaExtraida(
        periodo_referencia=periodo,
        data_vencimento=vencimento,
        valor_total_declarado=total,
        itens=itens,
        confidence_cabecalho=confidence_cabecalho,
    )
