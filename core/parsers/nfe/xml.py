"""Parser NF-e XML — Etapa 3.

Extrai campos fiscais da NF-e para alimentar o Motor de Classificação
sem depender de LLM. Quanto mais campos extraídos, mais precisa a
identificação de conta contábil por regra determinística.

Namespace padrão NF-e: http://www.portalfiscal.inf.br/nfe
Suporta: nfeProc (NF-e processada pela SEFAZ) e NFe direta.
"""

import hashlib
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from core.domain.entities import (
    CNPJ,
    ConfidenceScore,
    Dinheiro,
    Documento,
    FonteExtracao,
    MetadadosNFe,
    NaturezaLancamento,
    TipoDocumento,
)

_NS = "http://www.portalfiscal.inf.br/nfe"
_TAG = "{" + _NS + "}"


class NFeInvalidaError(Exception):
    pass


def parsear_nfe(filepath: Path) -> Documento:
    """Parseia um arquivo XML de NF-e e retorna um Documento enriquecido."""
    if not filepath.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        raise NFeInvalidaError(f"XML malformado: {filepath.name} — {e}") from e

    root = tree.getroot()
    nfe = _encontrar_nfe(root)
    if nfe is None:
        raise NFeInvalidaError(f"Elemento <NFe> não encontrado: {filepath.name}")

    inf = nfe.find(f"{_TAG}infNFe")
    if inf is None:
        raise NFeInvalidaError(f"Elemento <infNFe> não encontrado: {filepath.name}")

    hash_doc = hashlib.sha256(filepath.read_bytes()).hexdigest()
    scores: list[ConfidenceScore] = []

    # --- Identificação ---
    ide = inf.find(f"{_TAG}ide")
    chave_acesso = inf.get("Id", "").replace("NFe", "")
    numero_doc    = _texto(ide, "nNF")
    nat_op_texto  = _texto(ide, "natOp") or ""
    finalidade    = int(_texto(ide, "finNFe") or "1")
    data_emissao  = _parsear_data(_texto(ide, "dhEmi") or _texto(ide, "dEmi"))

    if chave_acesso:
        scores.append(ConfidenceScore(1.0, "chave_acesso"))
    if data_emissao:
        scores.append(ConfidenceScore(1.0, "data_emissao"))

    # --- Emitente ---
    emit         = inf.find(f"{_TAG}emit")
    cnpj_emit    = _parsear_cnpj(_texto(emit, "CNPJ"))
    nome_emit    = _texto(emit, "xNome")
    if cnpj_emit:
        scores.append(ConfidenceScore(1.0, "cnpj_emitente"))

    # --- Destinatário ---
    dest          = inf.find(f"{_TAG}dest")
    cnpj_dest     = _parsear_cnpj(_texto(dest, "CNPJ")) if dest is not None else None

    # --- Totais ---
    total         = inf.find(f"{_TAG}total/{_TAG}ICMSTot")
    valor_nfe     = _decimal(_texto(total, "vNF"))
    valor_prod    = _decimal(_texto(total, "vProd"))
    valor_desc    = _decimal(_texto(total, "vDesc"))
    valor_icms    = _decimal(_texto(total, "vICMS"))
    valor_pis     = _decimal(_texto(total, "vPIS"))
    valor_cofins  = _decimal(_texto(total, "vCOFINS"))
    valor_ipi     = _decimal(_texto(total, "vIPI"))
    valor_frete   = _decimal(_texto(total, "vFrete"))

    if valor_nfe > Decimal("0"):
        scores.append(ConfidenceScore(1.0, "valor_total"))

    # --- Itens: CFOP, NCM, CST ---
    cfop_itens: list[str] = []
    ncm_itens: list[str]  = []
    cst_lista: list[str]  = []

    for det in inf.findall(f"{_TAG}det"):
        prod = det.find(f"{_TAG}prod")
        if prod is not None:
            cfop = _texto(prod, "CFOP")
            ncm  = _texto(prod, "NCM")
            if cfop:
                cfop_itens.append(cfop)
            if ncm:
                ncm_itens.append(ncm)

        imposto = det.find(f"{_TAG}imposto")
        if imposto is not None:
            # CST (regime normal) ou CSOSN (Simples Nacional)
            cst = (
                _texto_path(imposto, f"{_TAG}ICMS//{_TAG}CST")
                or _texto_path(imposto, f"{_TAG}ICMS//{_TAG}CSOSN")
            )
            if cst:
                cst_lista.append(cst)

    if cfop_itens:
        scores.append(ConfidenceScore(1.0, "cfop"))
    if ncm_itens:
        scores.append(ConfidenceScore(0.95, "ncm"))

    cst_predominante = _predominante(cst_lista)
    cfop_predominante = _predominante(cfop_itens)

    # --- Natureza da operação por CFOP ---
    natureza = _natureza_por_cfop(cfop_predominante)

    # --- MetadadosNFe ---
    metadados = MetadadosNFe(
        chave_acesso=chave_acesso,
        finalidade=finalidade,
        natureza_operacao_texto=nat_op_texto,
        cfop_itens=tuple(cfop_itens),
        ncm_itens=tuple(ncm_itens),
        cst_icms=cst_predominante,
        cnpj_destinatario=cnpj_dest,
        valor_icms=Dinheiro(valor_icms),
        valor_pis=Dinheiro(valor_pis),
        valor_cofins=Dinheiro(valor_cofins),
        valor_ipi=Dinheiro(valor_ipi),
    )

    valor_liquido = valor_nfe - valor_desc if valor_nfe > Decimal("0") else Decimal("0")

    return Documento(
        hash_sha256=hash_doc,
        nome_arquivo=filepath.name,
        tipo=TipoDocumento.NFE_XML,
        fonte_extracao=FonteExtracao.XML,
        cnpj_emitente=cnpj_emit,
        nome_emitente=nome_emit,
        data_emissao=data_emissao,
        valor_total=Dinheiro(valor_nfe) if valor_nfe > Decimal("0") else None,
        valor_desconto=Dinheiro(valor_desc),
        valor_liquido=Dinheiro(valor_liquido) if valor_liquido > Decimal("0") else None,
        chave_acesso=chave_acesso or None,
        numero_documento=numero_doc,
        cfop=cfop_predominante,
        natureza_operacao=natureza,
        metadados_nfe=metadados,
        confidence_scores=scores,
        precisa_revisao=not bool(chave_acesso and data_emissao and valor_nfe),
        motivo_revisao=_motivo_revisao(chave_acesso, data_emissao, valor_nfe),
    )


# =============================================================
# HELPERS PRIVADOS
# =============================================================

def _encontrar_nfe(root: ET.Element) -> Optional[ET.Element]:
    """Suporta nfeProc (processada) e NFe direta."""
    tag_local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_local == "NFe":
        return root
    # nfeProc contém NFe como filho
    nfe = root.find(f"{_TAG}NFe")
    if nfe is not None:
        return nfe
    # fallback: qualquer namespace
    for child in root:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "NFe":
            return child
    return None


def _texto(element: Optional[ET.Element], tag: str) -> Optional[str]:
    if element is None:
        return None
    el = element.find(f"{_TAG}{tag}")
    if el is not None and el.text:
        return el.text.strip()
    return None


def _texto_path(element: ET.Element, path: str) -> Optional[str]:
    el = element.find(path)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _decimal(valor: Optional[str]) -> Decimal:
    if not valor:
        return Decimal("0")
    try:
        return Decimal(valor.replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _parsear_data(texto: Optional[str]) -> Optional[date]:
    if not texto:
        return None
    # dhEmi: "2024-03-15T10:30:00-03:00" ou "2024-03-15"
    texto = texto[:10]
    try:
        from datetime import datetime
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parsear_cnpj(texto: Optional[str]) -> Optional[CNPJ]:
    if not texto:
        return None
    digits = "".join(c for c in texto if c.isdigit())
    if len(digits) != 14:
        return None
    try:
        return CNPJ(digits)
    except ValueError:
        return None


def _predominante(lista: list[str]) -> Optional[str]:
    if not lista:
        return None
    return Counter(lista).most_common(1)[0][0]


def _natureza_por_cfop(cfop: Optional[str]) -> Optional[NaturezaLancamento]:
    """Determina natureza da operação pelo primeiro dígito do CFOP.

    1/2 = entrada (compra/recebimento)
    3   = entrada importação
    5/6 = saída (venda/remessa)
    7   = saída exportação
    """
    if not cfop:
        return None
    primeiro = cfop[0]
    if primeiro in ("1", "2", "3"):
        return NaturezaLancamento.DEBITO   # entrada = saída de caixa
    if primeiro in ("5", "6", "7"):
        return NaturezaLancamento.CREDITO  # saída = entrada de caixa
    return None


def _motivo_revisao(
    chave: str,
    data: Optional[date],
    valor: Decimal,
) -> Optional[str]:
    problemas = []
    if not chave:
        problemas.append("chave de acesso ausente")
    if not data:
        problemas.append("data de emissão ausente")
    if valor == Decimal("0"):
        problemas.append("valor total zero")
    return "; ".join(problemas) if problemas else None
