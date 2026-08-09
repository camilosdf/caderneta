"""MotorConciliacao — matching determinístico em camadas (Etapa 8.2).

Implementa o Motor 5 conforme o parecer arquitetural da Etapa 8:

  Camada 1: FITID / referência bancária (match exato)
  Camada 2: valor + data (dentro das tolerâncias configuradas)
  Camada 3: descrição normalizada (evidência adicional, não critério único)
  Decisão: unicidade → CONCILIADO | AMBIGUO | SEM_MATCH

Princípios mantidos (parecer Etapa 8):
  - Matching um-para-um: uma TransacaoBancaria ↔ um Lancamento
  - Candidatos produzidos ANTES da decisão (permite distinguir AMBIGUO)
  - Motor não depende de IA — classificação é responsabilidade do Motor 3
  - Motor pode ser testado sem banco, arquivo ou rede
  - Descrição normalizada é consumida, não produzida aqui

Tolerâncias padrão (configuráveis):
  - Valor: ± R$ 0,10
  - Data:  ± 2 dias
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from core.domain.entities import (
    CandidatoMatch,
    ConciliacaoItem,
    Lancamento,
    MetodoMatching,
    RelatorioConciliacao,
    TipoConciliacao,
    TransacaoBancaria,
)


@dataclass
class ToleranciasConciliacao:
    """Tolerâncias para matching por valor e data.

    Valores padrão conforme o plano do projeto (parecer Etapa 8):
      valor: ± R$ 0,10
      data:  ± 2 dias
    """
    valor: Decimal = Decimal("0.10")
    dias: int = 2


class MotorConciliacao:
    """Motor determinístico de conciliação bancária.

    Recebe lançamentos (visão Caderneta) e transações bancárias (visão banco)
    e produz um RelatorioConciliacao com a decisão para cada item.

    Nunca importa bibliotecas de infraestrutura (OFX, SQLAlchemy, etc.) —
    trabalha exclusivamente com entidades de domínio.
    """

    def __init__(
        self,
        tolerancias: ToleranciasConciliacao | None = None,
    ) -> None:
        self._tol = tolerancias or ToleranciasConciliacao()

    # ── API pública ───────────────────────────────────────────────────────

    def conciliar(
        self,
        lancamentos: list[Lancamento],
        transacoes: list[TransacaoBancaria],
        empresa_id: UUID,
        periodo_inicio: date,
        periodo_fim: date,
    ) -> RelatorioConciliacao:
        """Executa a conciliação e retorna o relatório completo.

        Matching é um-para-um: cada transação e cada lançamento aparecem
        em no máximo um item do relatório (invariante de domínio).
        """
        relatorio = RelatorioConciliacao(
            empresa_id=empresa_id,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
        )

        # Conjuntos de controle de unicidade
        lancamentos_usados: set[UUID] = set()
        transacoes_usadas: set[UUID] = set()

        # ── Fase 1: associar cada transação ao seu melhor match ───────────
        for tx in transacoes:
            candidatos = self._buscar_candidatos(tx, lancamentos, lancamentos_usados)
            item = self._decidir(tx, candidatos)

            if item.lancamento_id is not None:
                lancamentos_usados.add(item.lancamento_id)
            transacoes_usadas.add(tx.id)

            relatorio.itens.append(item)

        # ── Fase 2: lançamentos sem transação correspondente → PENDENTE ───
        for lanc in lancamentos:
            if lanc.id not in lancamentos_usados:
                relatorio.itens.append(ConciliacaoItem(
                    lancamento_id=lanc.id,
                    transacao_bancaria_id=None,
                    status=TipoConciliacao.PENDENTE,
                    metodo=MetodoMatching.SEM_MATCH,
                    score=0.0,
                    justificativa="Lançamento sem movimento bancário correspondente no extrato.",
                ))

        return relatorio

    # ── Matching em camadas ───────────────────────────────────────────────

    def _buscar_candidatos(
        self,
        tx: TransacaoBancaria,
        lancamentos: list[Lancamento],
        usados: set[UUID],
    ) -> list[CandidatoMatch]:
        """Produz candidatos em ordem decrescente de score.

        Não decide — apenas ranqueia. A decisão fica em _decidir().
        """
        candidatos: list[CandidatoMatch] = []

        for lanc in lancamentos:
            if lanc.id in usados:
                continue  # já conciliado com outra transação

            candidato = self._avaliar_par(tx, lanc)
            if candidato is not None:
                candidatos.append(candidato)

        return sorted(candidatos, key=lambda c: c.score, reverse=True)

    def _avaliar_par(
        self,
        tx: TransacaoBancaria,
        lanc: Lancamento,
    ) -> CandidatoMatch | None:
        """Avalia um par (transação, lançamento) e retorna candidato ou None.

        Camadas de matching (em ordem de prioridade):
          1. FITID: se o lançamento registra o FITID, é match exato
          2. Valor + Data: dentro das tolerâncias configuradas
          3. Descrição: evidência adicional que aumenta o score
        """
        evidencias: list[str] = []
        metodo = MetodoMatching.SEM_MATCH
        score = 0.0
        diferenca_valor = Decimal("0")
        diferenca_dias = 0

        # ── Camada 1: FITID ───────────────────────────────────────────────
        # numero_documento no Lancamento pode carregar o FITID original
        # (via OFXParser que armazena transacao.id em numero_documento)
        fitid_lanc = self._fitid_do_lancamento(lanc)
        if fitid_lanc and fitid_lanc == tx.fitid:
            return CandidatoMatch(
                lancamento_id=lanc.id,
                metodo=MetodoMatching.FITID,
                score=1.0,
                diferenca_valor=Decimal("0"),
                diferenca_dias=0,
                evidencias=["FITID coincide exatamente"],
            )

        # ── Camada 2: Valor + Data ────────────────────────────────────────
        dif_valor = abs(tx.valor.valor - lanc.valor_total.valor)
        if dif_valor > self._tol.valor:
            return None  # diferença de valor acima da tolerância → não é candidato

        dif_dias = self._diferenca_dias(tx.data, lanc)
        if dif_dias > self._tol.dias:
            return None  # diferença de data acima da tolerância → não é candidato

        diferenca_valor = dif_valor
        diferenca_dias = dif_dias
        metodo = MetodoMatching.VALOR_DATA
        score = self._score_valor_data(dif_valor, dif_dias)

        evidencias.append(
            f"valor dentro da tolerância (Δ={dif_valor:.2f})"
        )
        evidencias.append(
            f"data dentro da tolerância (Δ={dif_dias}d)"
        )

        # ── Camada 3: Descrição (evidência adicional) ─────────────────────
        if tx.descricao and lanc.descricao:
            sim = _similaridade_descricao(tx.descricao, lanc.descricao)
            if sim > 0.5:
                score = min(1.0, score + sim * 0.2)
                metodo = MetodoMatching.VALOR_DATA_DESCRICAO
                evidencias.append(
                    f"descrição similar (sim={sim:.2f}): "
                    f"'{tx.descricao[:30]}' ~ '{lanc.descricao[:30]}'"
                )

        return CandidatoMatch(
            lancamento_id=lanc.id,
            metodo=metodo,
            score=round(score, 4),
            diferenca_valor=diferenca_valor,
            diferenca_dias=diferenca_dias,
            evidencias=evidencias,
        )

    # ── Decisão final ─────────────────────────────────────────────────────

    def _decidir(
        self,
        tx: TransacaoBancaria,
        candidatos: list[CandidatoMatch],
    ) -> ConciliacaoItem:
        """Transforma candidatos em decisão final para uma transação.

        Regras:
          0 candidatos  → SEM_DOCUMENTO
          1 candidato   → avaliar tolerâncias → CONCILIADO ou DIVERGENTE
          >1 candidatos → AMBIGUO (nunca escolhe arbitrariamente)
        """
        item = ConciliacaoItem(
            transacao_bancaria_id=tx.id,
            candidatos=candidatos,
        )

        if not candidatos:
            item.status = TipoConciliacao.SEM_DOCUMENTO
            item.metodo = MetodoMatching.SEM_MATCH
            item.justificativa = "Nenhum lançamento compatível encontrado no período."
            return item

        melhor = candidatos[0]

        # Candidato por FITID → sempre CONCILIADO (match exato)
        if melhor.metodo == MetodoMatching.FITID:
            item.lancamento_id = melhor.lancamento_id
            item.status = TipoConciliacao.CONCILIADO
            item.metodo = MetodoMatching.FITID
            item.score = 1.0
            item.justificativa = "Match exato por FITID."
            return item

        # Mais de um candidato com scores próximos → AMBIGUO
        if len(candidatos) > 1:
            segundo = candidatos[1]
            if abs(melhor.score - segundo.score) < 0.05:
                item.status = TipoConciliacao.AMBIGUO
                item.metodo = melhor.metodo
                item.score = melhor.score
                item.justificativa = (
                    f"{len(candidatos)} candidatos equivalentes — revisão humana necessária."
                )
                return item

        # Candidato único ou claramente melhor
        item.lancamento_id = melhor.lancamento_id
        item.metodo = melhor.metodo
        item.score = melhor.score
        item.diferenca_valor = melhor.diferenca_valor
        item.diferenca_dias = melhor.diferenca_dias

        # Divergência: houve match mas com diferença relevante
        tem_divergencia = (
            melhor.diferenca_valor > Decimal("0.01")
            or melhor.diferenca_dias > 0
        )

        if tem_divergencia:
            item.status = TipoConciliacao.DIVERGENTE
            item.justificativa = (
                f"Match com divergência: "
                f"Δvalor=R${melhor.diferenca_valor:.2f}, "
                f"Δdata={melhor.diferenca_dias}d."
            )
        else:
            item.status = TipoConciliacao.CONCILIADO
            item.justificativa = "Conciliado automaticamente por valor e data."

        return item

    # ── Utilitários internos ──────────────────────────────────────────────

    def _fitid_do_lancamento(self, lanc: Lancamento) -> str | None:
        """Extrai o FITID do lançamento se disponível.

        O OFXParser armazena o FITID em Documento.numero_documento.
        O lançamento pode ter sido gerado a partir de um Documento OFX
        cujo numero_documento era o FITID original.
        """
        # Acesso direto se o lançamento tiver referência OFX
        if hasattr(lanc, "numero_documento_origem"):
            return lanc.numero_documento_origem
        return None

    def _diferenca_dias(self, data_tx: date, lanc: Lancamento) -> int:
        """Diferença em dias entre a transação bancária e o lançamento."""
        data_lanc = lanc.data_lancamento
        if data_lanc is None:
            return self._tol.dias + 1  # sem data → fora da tolerância
        return abs((data_tx - data_lanc).days)

    def _score_valor_data(self, dif_valor: Decimal, dif_dias: int) -> float:
        """Score base para match por valor+data (sem FITID).

        Quanto menor a diferença, maior o score. Base de 0.7 para
        qualquer match dentro da tolerância, com bônus para correspondência
        exata ou quase exata.
        """
        score = 0.70

        # Bônus por proximidade de valor
        if dif_valor == Decimal("0"):
            score += 0.15
        elif dif_valor <= Decimal("0.01"):
            score += 0.10
        elif dif_valor <= Decimal("0.05"):
            score += 0.05

        # Bônus por proximidade de data
        if dif_dias == 0:
            score += 0.10
        elif dif_dias == 1:
            score += 0.05

        return min(score, 0.95)  # FITID é o único que pode atingir 1.0


# =============================================================
# UTILITÁRIO DE SIMILARIDADE DE DESCRIÇÃO
# =============================================================

def _similaridade_descricao(a: str, b: str) -> float:
    """Similaridade simples entre descrições — Jaccard de trigramas.

    Não depende de IA nem de modelos de linguagem. É uma heurística
    determinística usada apenas como evidência adicional no Motor 5 —
    nunca como critério único de matching.

    Por que trigramas em vez de palavras?
    Extratos bancários frequentemente truncam ou abreviam nomes:
      "UBER DO BRASIL" vs "UBER*VIAGEM" — trigramas capturam a raiz "UBE"
    """
    a_clean = _normalizar(a)
    b_clean = _normalizar(b)

    if not a_clean or not b_clean:
        return 0.0

    trigramas_a = _trigramas(a_clean)
    trigramas_b = _trigramas(b_clean)

    if not trigramas_a or not trigramas_b:
        return 0.0

    intersecao = trigramas_a & trigramas_b
    uniao = trigramas_a | trigramas_b
    return len(intersecao) / len(uniao)


def _normalizar(texto: str) -> str:
    """Remove pontuação, converte para maiúsculas, normaliza espaços."""
    import re
    texto = re.sub(r"[^\w\s]", " ", texto.upper())
    return re.sub(r"\s+", " ", texto).strip()


def _trigramas(texto: str) -> set[str]:
    """Conjunto de trigramas de um texto normalizado."""
    palavras = texto.split()
    texto_concat = " ".join(palavras)
    return {texto_concat[i:i+3] for i in range(len(texto_concat) - 2)}
