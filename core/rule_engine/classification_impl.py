"""Implementação padrão do ClassificationPort — apenas regras determinísticas.

Esta implementação funciona sem nenhum componente de IA.
É a implementação usada nas Etapas 1 a 6.
Na Etapa 7, EmbeddingsPlugin e LLMPlugin são adicionados como camadas adicionais.
"""

import re
import unicodedata
from typing import Any, Optional

from core.domain.entities import (
    CodigoConta,
    Documento,
    Fornecedor,
    NaturezaLancamento,
    RegraClassificacao,
)
from core.ports.classification import (
    ClassificationPort,
    ResultadoNormalizacao,
    Sugestao,
)


class RegrasDeterministicasPlugin:
    """
    Implementa ClassificationPort usando regras parametrizáveis.
    Satisfaz o Protocol sem herdar dele — duck typing estrutural.
    """

    def __init__(
        self,
        regras: list[Any],  # aceita RegraClassificacao ou RegraClassificacaoV2
        fornecedores: list[Fornecedor],
        conta_fallback_debito: str = "4.1.01.099",
        conta_fallback_credito: str = "1.1.01.002",
    ):
        self._regras = sorted(regras, key=lambda r: r.prioridade)
        self._fornecedores = fornecedores
        self._conta_fallback_debito = CodigoConta(conta_fallback_debito)
        self._conta_fallback_credito = CodigoConta(conta_fallback_credito)

        # Índices para busca rápida de fornecedores
        self._indice_exato: dict[str, Fornecedor] = {}
        self._indice_alias: dict[str, Fornecedor] = {}
        self._construir_indices()

    # ── ClassificationPort ────────────────────────────────────────────────

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Optional[Fornecedor],
    ) -> Sugestao:
        """Aplica regras em ordem de prioridade. Primeira que bater, ganha."""

        descricao = (documento.nome_emitente or "").upper()

        for regra in self._regras:
            if not regra.ativa:
                continue
            if self._avaliar(regra, documento, descricao, fornecedor):
                return Sugestao(
                    categoria=regra.categoria,
                    conta_debito=regra.conta_debito,
                    conta_credito=regra.conta_credito,
                    centro_custo=regra.centro_custo,
                    confidence=1.0,
                    metodo="regra_deterministica",
                    regra_aplicada_id=regra.id,
                    versao_regra=regra.versao,
                    precisa_revisao=False,
                )

        # Nenhuma regra cobriu — fallback para revisão humana
        return Sugestao(
            categoria="Outras Despesas",
            conta_debito=self._conta_fallback_debito,
            conta_credito=self._conta_fallback_credito,
            centro_custo=None,
            confidence=0.0,
            metodo="fallback",
            precisa_revisao=True,
            motivo="Nenhuma regra aplicável. Revisão humana necessária.",
        )

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normaliza nome bruto contra a base de fornecedores conhecidos."""

        if not nome_raw or not nome_raw.strip():
            return ResultadoNormalizacao(
                fornecedor_id=None,
                nome_canonico="SEM DESCRIÇÃO",
                confidence=0.0,
                metodo="vazio",
                precisa_revisao=True,
            )

        chave = self._normalizar_texto(nome_raw)

        # 1. Busca exata
        if chave in self._indice_exato:
            f = self._indice_exato[chave]
            return ResultadoNormalizacao(
                fornecedor_id=f.id,
                nome_canonico=f.nome_canonico,
                confidence=1.0,
                metodo="exato",
            )

        # 2. Busca por alias
        if chave in self._indice_alias:
            f = self._indice_alias[chave]
            return ResultadoNormalizacao(
                fornecedor_id=f.id,
                nome_canonico=f.nome_canonico,
                confidence=0.98,
                metodo="alias",
            )

        # 3. Busca por prefixo (ex: "UBER *TRIP 12345" → "UBER")
        for chave_idx, fornecedor in self._indice_exato.items():
            if len(chave_idx) >= 4 and (
                chave.startswith(chave_idx) or chave_idx.startswith(chave)
            ):
                return ResultadoNormalizacao(
                    fornecedor_id=fornecedor.id,
                    nome_canonico=fornecedor.nome_canonico,
                    confidence=0.85,
                    metodo="prefixo",
                )

        # 4. Novo fornecedor — vai para revisão
        return ResultadoNormalizacao(
            fornecedor_id=None,
            nome_canonico=nome_raw.strip().upper(),
            confidence=0.0,
            metodo="novo",
            precisa_revisao=True,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _avaliar(
        self,
        regra: RegraClassificacao,
        documento: Documento,
        descricao: str,
        fornecedor: Optional[Fornecedor],
    ) -> bool:
        c = regra.condicao

        if "descricao_contains_any" in c:
            termos = c["descricao_contains_any"]
            if not any(t.upper() in descricao for t in termos):
                return False

        if "cfop" in c:
            if documento.cfop != c["cfop"]:
                return False

        if "tipo_lancamento" in c:
            tipo = c["tipo_lancamento"]
            if tipo == "credito" and documento.natureza_operacao != NaturezaLancamento.CREDITO:
                return False
            if tipo == "debito" and documento.natureza_operacao != NaturezaLancamento.DEBITO:
                return False

        if "fornecedor_categoria" in c and fornecedor:
            if fornecedor.categoria != c["fornecedor_categoria"]:
                return False

        return True

    def _construir_indices(self) -> None:
        for f in self._fornecedores:
            self._indice_exato[self._normalizar_texto(f.nome_canonico)] = f
            for alias in f.aliases:
                self._indice_alias[self._normalizar_texto(alias)] = f

    @staticmethod
    def _normalizar_texto(texto: str) -> str:
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        texto = texto.upper()
        texto = re.sub(r"\*+", " ", texto)
        texto = re.sub(r"^\d+\s+", "", texto)
        texto = re.sub(r"\s+\d{6,}", "", texto)
        texto = re.sub(r"[^\w\s]", " ", texto)
        texto = re.sub(r"\s+", " ", texto)
        return texto.strip()


# Verificação estática de que RegrasDeterministicasPlugin satisfaz o Protocol
def _verificar_contrato() -> None:
    assert isinstance(RegrasDeterministicasPlugin([], []), ClassificationPort), (
        "RegrasDeterministicasPlugin não satisfaz ClassificationPort"
    )
