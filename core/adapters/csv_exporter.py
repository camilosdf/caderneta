"""Exportador CSV Auditado — Emenda E-10, CLI First.

Disponível desde a Etapa 4, antes da interface web.
O contador pode operar o sistema inteiro via CLI + CSV + GnuCash manual.
A interface web (Etapa 6) é melhoria de UX, não pré-requisito.
"""

import csv
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from core.domain.entities import Lancamento, NaturezaLancamento


COLUNAS_GNUCASH = [
    "Date",
    "Description",
    "Notes",
    "Account",
    "Deposit",
    "Withdrawal",
    "Balance",
    "Category",
]


class ExportadorCSV:
    """Exporta lançamentos para CSV compatível com GnuCash e registra metadados."""

    def exportar(
        self,
        lancamentos: list[Lancamento],
        pasta_saida: Path,
        prefixo: str = "caderneta",
        aprovado_por: str | None = None,
    ) -> "ResultadoExportacao":

        pasta_saida.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"{prefixo}_{timestamp}.csv"
        caminho = pasta_saida / nome_arquivo

        # Conferência antes de exportar
        conferencia = self._conferir(lancamentos)
        if not conferencia.valido:
            raise ValueError(
                f"Conferência falhou antes da exportação:\n"
                + "\n".join(f"  • {e}" for e in conferencia.erros)
            )

        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(COLUNAS_GNUCASH)
            for lancamento in lancamentos:
                for linha in self._splits_para_linhas(lancamento):
                    writer.writerow(linha)

        hash_csv = self._hash_arquivo(caminho)

        return ResultadoExportacao(
            caminho=caminho,
            hash_sha256=hash_csv,
            total_lancamentos=len(lancamentos),
            total_valor=sum(l.valor_total.valor for l in lancamentos),
            aprovado_por=aprovado_por,
            conferencia=conferencia,
        )

    def _splits_para_linhas(self, lancamento: Lancamento) -> list[list[str]]:
        """Converte splits do lançamento em linhas CSV (uma por split)."""
        data_str = lancamento.data_lancamento.strftime("%d/%m/%Y") if lancamento.data_lancamento else ""
        descricao = lancamento.historico_padronizado or lancamento.descricao
        if lancamento.e_parcelado and lancamento.parcela_atual and lancamento.total_parcelas:
            descricao = f"{descricao} ({lancamento.parcela_atual}/{lancamento.total_parcelas})"

        notas = f"Caderneta v0.2"
        if lancamento.confidence is not None:
            notas += f" | Confiança: {lancamento.confidence:.0%}"
        if lancamento.metodo_classificacao:
            notas += f" | {lancamento.metodo_classificacao}"

        linhas = []
        for split in lancamento.splits:
            deposit   = _fmt(split.valor.valor) if split.natureza == NaturezaLancamento.DEBITO else ""
            withdrawal = _fmt(split.valor.valor) if split.natureza == NaturezaLancamento.CREDITO else ""
            linhas.append([
                data_str,
                descricao[:80],
                notas,
                split.conta.codigo,
                deposit,
                withdrawal,
                "",
                lancamento.categoria or "",
            ])
        return linhas

    def _conferir(self, lancamentos: list[Lancamento]) -> "Conferencia":
        erros: list[str] = []
        avisos: list[str] = []
        total = Decimal("0")

        for l in lancamentos:
            if not l.splits:
                erros.append(f"Lançamento '{l.descricao[:40]}': sem splits.")
                continue
            try:
                l.validar()  # verifica partidas dobradas
            except ValueError as e:
                erros.append(str(e))

            total += l.valor_total.valor

            if l.confidence is not None and l.confidence < 0.90:
                avisos.append(
                    f"'{l.descricao[:35]}': confiança baixa ({l.confidence:.0%})"
                )

        return Conferencia(
            valido=len(erros) == 0,
            total_lancamentos=len(lancamentos),
            total_valor=total,
            erros=erros,
            avisos=avisos,
        )

    @staticmethod
    def _hash_arquivo(caminho: Path) -> str:
        sha = hashlib.sha256()
        with open(caminho, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()


class Conferencia:
    def __init__(
        self,
        valido: bool,
        total_lancamentos: int,
        total_valor: Decimal,
        erros: list[str],
        avisos: list[str],
    ):
        self.valido = valido
        self.total_lancamentos = total_lancamentos
        self.total_valor = total_valor
        self.erros = erros
        self.avisos = avisos

    def __str__(self) -> str:
        status = "✅ VÁLIDO" if self.valido else "❌ INVÁLIDO"
        linhas = [
            f"{status} — {self.total_lancamentos} lançamentos | "
            f"R$ {self.total_valor:,.2f}",
        ]
        if self.erros:
            linhas += [f"  ❌ {e}" for e in self.erros]
        if self.avisos:
            linhas += [f"  ⚠  {a}" for a in self.avisos]
        return "\n".join(linhas)


class ResultadoExportacao:
    def __init__(
        self,
        caminho: Path,
        hash_sha256: str,
        total_lancamentos: int,
        total_valor: Decimal,
        conferencia: "Conferencia",
        aprovado_por: str | None = None,
    ):
        self.caminho = caminho
        self.hash_sha256 = hash_sha256
        self.total_lancamentos = total_lancamentos
        self.total_valor = total_valor
        self.conferencia = conferencia
        self.aprovado_por = aprovado_por
        self.exportado_em = datetime.now(timezone.utc)

    def __str__(self) -> str:
        return (
            f"CSV gerado: {self.caminho.name}\n"
            f"Hash SHA-256: {self.hash_sha256}\n"
            f"Lançamentos: {self.total_lancamentos} | "
            f"Total: R$ {self.total_valor:,.2f}\n"
            + str(self.conferencia)
        )


def _fmt(valor: Decimal) -> str:
    return f"{abs(valor):.2f}".replace(".", ",")
