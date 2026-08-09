"""LLMPlugin — desambiguação via LLM (Etapa 7.5).

Terceira e última camada do ClassifierOrchestrator:

  Regras (confidence=1.0) → Embeddings (≥0.85) → LLM (desambiguação)

Só é ativado quando regras + embeddings não cobriram o caso com
confiança suficiente. Nunca decide sozinho — retorna sempre com
precisa_revisao=True quando confidence < threshold definido.

Princípios (ADR 003):
  - LLM é auxiliar, não decisor
  - Toda sugestão de LLM fica em revisão humana por padrão
  - confidence=1.0 é impossível aqui — reservado para regras determinísticas
  - O prompt inclui contexto contábil, mas a decisão final é do contador

Formato de resposta esperado do LLM:
  JSON com campos: categoria, conta_debito, conta_credito, confidence, motivo
  Campos ausentes → fallback seguro (precisa_revisao=True, confidence baixo)
"""

import json
import logging

from core.domain.entities import CodigoConta, Documento, Fornecedor
from core.ports.classification import ResultadoNormalizacao, Sugestao
from core.ports.llm import LLMPort

logger = logging.getLogger(__name__)

_PROMPT_CLASSIFICACAO = """\
Você é um assistente de classificação contábil para empresas brasileiras.
Classifique o lançamento abaixo segundo o Plano de Contas e retorne APENAS JSON válido.

Documento:
  Emitente: {nome_emitente}
  Valor: R$ {valor}
  Tipo: {tipo}

Retorne exatamente neste formato JSON (sem markdown, sem texto adicional):
{{
  "categoria": "<categoria contábil>",
  "conta_debito": "<código da conta de débito, ex: 4.1.01.001>",
  "conta_credito": "<código da conta de crédito, ex: 1.1.01.002>",
  "confidence": <número entre 0.0 e 0.95>,
  "motivo": "<explicação em uma frase>"
}}

Se não tiver certeza, use confidence < 0.7 para sinalizar revisão obrigatória.
"""


class LLMPlugin:
    """Implementa ClassificationPort via LLM para desambiguação.

    Satisfaz ClassificationPort via duck typing — não herda de nenhuma
    classe base, mesma disciplina dos outros plugins.
    """

    def __init__(
        self,
        provider: LLMPort,
        conta_fallback_debito: str = "4.1.01.099",
        conta_fallback_credito: str = "1.1.01.002",
        threshold_revisao: float = 0.75,
        max_tokens: int = 256,
    ) -> None:
        self._provider = provider
        self._conta_fallback_debito = CodigoConta(conta_fallback_debito)
        self._conta_fallback_credito = CodigoConta(conta_fallback_credito)
        self._threshold_revisao = threshold_revisao
        self._max_tokens = max_tokens

    # ── ClassificationPort ────────────────────────────────────────────────

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Fornecedor | None,
    ) -> Sugestao:
        """Consulta o LLM para classificar um documento não coberto por
        regras nem embeddings. Sempre retorna precisa_revisao=True
        quando confidence < threshold_revisao."""
        prompt = _PROMPT_CLASSIFICACAO.format(
            nome_emitente=documento.nome_emitente or "Desconhecido",
            valor=documento.valor_total.valor if documento.valor_total else "0.00",
            tipo=documento.tipo.value if documento.tipo else "desconhecido",
        )

        try:
            resposta = self._provider.completar(
                prompt=prompt,
                max_tokens=self._max_tokens,
                temperatura=0.0,
            )
            return self._parsear_resposta(resposta)
        except Exception as e:
            logger.warning("LLMPlugin: erro ao consultar provider: %s", e)
            return self._fallback(motivo=f"Erro na consulta ao LLM: {e}")

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normalização via LLM — fora do escopo desta etapa. Retorna
        o nome bruto com precisa_revisao=True para não bloquear o pipeline."""
        return ResultadoNormalizacao(
            fornecedor_id=None,
            nome_canonico=nome_raw,
            confidence=0.0,
            metodo="llm",
            precisa_revisao=True,
        )

    # ── Internos ──────────────────────────────────────────────────────────

    def _parsear_resposta(self, resposta: str) -> Sugestao:
        """Parseia o JSON do LLM com fallback seguro para qualquer erro."""
        try:
            dados = json.loads(resposta.strip())
        except (json.JSONDecodeError, ValueError):
            return self._fallback(motivo="Resposta do LLM não é JSON válido.")

        confidence = float(dados.get("confidence", 0.0))
        # LLM nunca pode afirmar confidence ≥ 1.0 — clipar para 0.98
        confidence = min(confidence, 0.98)

        conta_debito_str = dados.get("conta_debito", "")
        conta_credito_str = dados.get("conta_credito", "")

        try:
            conta_debito = CodigoConta(conta_debito_str) if conta_debito_str else self._conta_fallback_debito
            conta_credito = CodigoConta(conta_credito_str) if conta_credito_str else self._conta_fallback_credito
        except Exception:
            conta_debito = self._conta_fallback_debito
            conta_credito = self._conta_fallback_credito

        return Sugestao(
            categoria=dados.get("categoria"),
            conta_debito=conta_debito,
            conta_credito=conta_credito,
            centro_custo=None,
            confidence=confidence,
            metodo=f"llm:{self._provider.modelo}",
            precisa_revisao=confidence < self._threshold_revisao,
            motivo=dados.get("motivo", "Classificado por LLM."),
        )

    def _fallback(self, motivo: str) -> Sugestao:
        return Sugestao(
            categoria=None,
            conta_debito=self._conta_fallback_debito,
            conta_credito=self._conta_fallback_credito,
            centro_custo=None,
            confidence=0.0,
            metodo=f"llm:{self._provider.modelo}",
            precisa_revisao=True,
            motivo=motivo,
        )
