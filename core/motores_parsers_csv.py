"""Parsers CSV para os principais bancos brasileiros.

Cada banco tem formato CSV diferente — por isso parsers dedicados,
não regex genérico. Adicionar novos bancos aqui conforme necessário.
"""

import csv
import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from core.domain.entities import ConfidenceScore, Documento as DocumentoFinanceiro, Dinheiro, FonteExtracao, NaturezaLancamento, TipoDocumento


class BancoNaoIdentificadoError(Exception):
    pass


def detectar_banco(filepath: Path) -> str:
    """Detecta o banco pelo cabeçalho do CSV."""
    with open(filepath, encoding="utf-8-sig", errors="ignore") as f:
        primeiras_linhas = [f.readline() for _ in range(5)]

    conteudo = "\n".join(primeiras_linhas).upper()

    if "INTER" in conteudo or "BANCO INTER" in conteudo:
        return "inter"
    if "ITAÚ" in conteudo or "ITAU" in conteudo:
        return "itau"
    if "BRADESCO" in conteudo:
        return "bradesco"
    if "NUBANK" in conteudo or "NU PAGAMENTOS" in conteudo:
        return "nubank"
    if "SANTANDER" in conteudo:
        return "santander"

    raise BancoNaoIdentificadoError(
        f"Banco não identificado no arquivo {filepath.name}. "
        f"Verifique se é um extrato CSV válido."
    )


def parsear_csv(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    """Detecta o banco e aplica o parser correto."""
    banco = detectar_banco(filepath)

    parsers = {
        "inter":     _parsear_inter,
        "itau":      _parsear_itau,
        "nubank":    _parsear_nubank,
        "bradesco":  _parsear_bradesco,
        "santander": _parsear_santander,
    }

    parser = parsers.get(banco)
    if not parser:
        raise BancoNaoIdentificadoError(f"Parser não implementado para: {banco}")

    yield from parser(filepath)


# =============================================================
# BANCO INTER
# Formato: Data;Tipo;Descrição;Valor
# =============================================================
def _parsear_inter(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = _parse_data_br(linha.get("Data", ""))
                valor_str = linha.get("Valor", "0").replace(".", "").replace(",", ".")
                valor = Decimal(valor_str)
                descricao = linha.get("Descrição", linha.get("Descricao", "")).strip()

                yield _criar_documento(filepath, data, valor, descricao, "inter")
            except (ValueError, InvalidOperation, KeyError):
                continue


# =============================================================
# ITAÚ
# Formato: Data;Lançamento;Valor;Saldo
# =============================================================
def _parsear_itau(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    with open(filepath, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = _parse_data_br(linha.get("Data", ""))
                descricao = linha.get("Lançamento", linha.get("Lancamento", "")).strip()
                valor_str = linha.get("Valor", "0").replace(".", "").replace(",", ".")
                valor = Decimal(valor_str)

                if not descricao or not data:
                    continue

                yield _criar_documento(filepath, data, valor, descricao, "itau")
            except (ValueError, InvalidOperation, KeyError):
                continue


# =============================================================
# NUBANK (Cartão de Crédito)
# Formato: date,title,amount (em inglês, vírgula, UTF-8)
# =============================================================
def _parsear_nubank(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")
        for linha in reader:
            try:
                data_str = linha.get("date", "")
                data = datetime.strptime(data_str, "%Y-%m-%d").date()
                descricao = linha.get("title", "").strip()
                valor_str = linha.get("amount", "0").replace(",", ".")
                valor = Decimal(valor_str)

                if not descricao:
                    continue

                yield _criar_documento(filepath, data, valor, descricao, "nubank")
            except (ValueError, InvalidOperation, KeyError):
                continue


# =============================================================
# BRADESCO
# Formato: Data;Histórico;Docto;Crédito (R$);Débito (R$);Saldo (R$)
# =============================================================
def _parsear_bradesco(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    with open(filepath, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = _parse_data_br(linha.get("Data", ""))
                descricao = linha.get("Histórico", linha.get("Historico", "")).strip()

                credito_str = linha.get("Crédito (R$)", "0").replace(".", "").replace(",", ".")
                debito_str  = linha.get("Débito (R$)",  "0").replace(".", "").replace(",", ".")

                credito = Decimal(credito_str or "0")
                debito  = Decimal(debito_str  or "0")

                if credito > 0:
                    valor = credito
                elif debito > 0:
                    valor = -debito
                else:
                    continue

                yield _criar_documento(filepath, data, valor, descricao, "bradesco")
            except (ValueError, InvalidOperation, KeyError):
                continue


# =============================================================
# SANTANDER
# Formato: Data;Histórico;Valor
# =============================================================
def _parsear_santander(filepath: Path) -> Iterator[DocumentoFinanceiro]:
    with open(filepath, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for linha in reader:
            try:
                data = _parse_data_br(linha.get("Data", ""))
                descricao = linha.get("Histórico", linha.get("Historico", "")).strip()
                valor_str = linha.get("Valor", "0").replace(".", "").replace(",", ".")
                valor = Decimal(valor_str)

                yield _criar_documento(filepath, data, valor, descricao, "santander")
            except (ValueError, InvalidOperation, KeyError):
                continue


# =============================================================
# HELPERS
# =============================================================
def _criar_documento(
    filepath: Path,
    data: date,
    valor: Decimal,
    descricao: str,
    banco: str,
) -> DocumentoFinanceiro:
    """Cria um DocumentoFinanceiro padronizado a partir dos campos extraídos."""
    chave = f"{banco}:{filepath.name}:{data}:{valor}:{descricao}"
    hash_doc = hashlib.sha256(chave.encode()).hexdigest()

    return DocumentoFinanceiro(
        tipo=TipoDocumento.CSV,
        nome_arquivo=filepath.name,
        hash_sha256=hash_doc,
        data_emissao=data,
        valor_total=abs(valor),
        valor_liquido=abs(valor),
        nome_emitente=descricao.upper().strip(),
        fonte_extracao=FonteExtracao.CSV,
        confidence_scores=[ConfidenceScore(1.0, "valor"), ConfidenceScore(1.0, "data"), ConfidenceScore(0.90, "descricao")],
        precisa_revisao=False,
        natureza_operacao=NaturezaLancamento.CREDITO if valor > 0 else NaturezaLancamento.DEBITO,
    )


def _parse_data_br(texto: str) -> date:
    """Interpreta datas no formato DD/MM/YYYY ou DD/MM/YY."""
    texto = texto.strip()
    formatos = ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data não reconhecida: {texto}")
