"""Entidade RegraClassificacao completa — campos de auditabilidade obrigatórios.

Incorpora todas as recomendações do comitê ampliado:
valid_from, valid_until, author, reason, audit_reference, explanation, confidence_threshold.

Uma regra precisa ser completamente auditável:
"Qual versão desta regra classificou este lançamento em março de 2026?"
deve ter resposta precisa e reproduzível.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

_UTC = timezone.utc


def _agora() -> datetime:
    return datetime.now(_UTC)
from typing import Optional
from uuid import uuid4

from core.domain.entities import CodigoConta


@dataclass
class RegraClassificacaoV2:
    """
    Regra de classificação contábil — versão completa com auditabilidade.
    Substitui a RegraClassificacao original no core/domain/entities.py.
    """

    # Identificação
    id: str = field(default_factory=lambda: str(uuid4()))
    empresa_id: str = ""
    nome: str = ""

    # Condição e resultado
    condicao: dict = field(default_factory=dict)
    categoria: str | None = None
    conta_debito: Optional[CodigoConta] = None
    conta_credito: Optional[CodigoConta] = None
    centro_custo: str | None = None

    # Prioridade e estado
    prioridade: int = 100
    ativa: bool = True

    # Versionamento obrigatório
    versao: int = 1
    versao_anterior_id: str | None = None   # aponta para a versão que esta substituiu

    # Vigência temporal
    valida_a_partir: datetime | None = None   # None = sempre válida desde criação
    valida_ate: datetime | None = None        # None = sem expiração

    # Auditoria de autoria
    criada_por: str = ""
    criada_em: datetime = field(default_factory=_agora)
    alterada_por: str | None = None
    alterada_em: datetime | None = None

    # Rastreabilidade da decisão
    reason: str = ""              # por que esta regra existe
    audit_reference: str = ""     # ex: "Resolução SEFAZ 45/2025", "RFB IN 2121/2022"
    explanation: str = ""         # explicação legível para o contador

    # Threshold de confiança da IA para esta regra entrar como fallback
    # (quando regras determinísticas não cobrem, a IA sugere com confidence)
    # None = regra determinística pura, nunca usa IA como fallback
    confidence_threshold: float | None = None

    def esta_vigente(self, momento: datetime | None = None) -> bool:
        """Verifica se a regra está vigente em um dado momento."""
        ref = momento or _agora()

        if self.valida_a_partir and ref < self.valida_a_partir:
            return False

        if self.valida_ate and ref > self.valida_ate:
            return False

        return self.ativa

    def criar_nova_versao(
        self,
        alterado_por: str,
        motivo_alteracao: str,
        **campos_alterados,
    ) -> "RegraClassificacaoV2":
        """
        Cria uma nova versão desta regra.
        A regra original NÃO é alterada — imutabilidade da história.
        """
        nova = RegraClassificacaoV2(
            empresa_id=self.empresa_id,
            nome=self.nome,
            condicao=self.condicao.copy(),
            categoria=self.categoria,
            conta_debito=self.conta_debito,
            conta_credito=self.conta_credito,
            centro_custo=self.centro_custo,
            prioridade=self.prioridade,
            ativa=True,
            versao=self.versao + 1,
            versao_anterior_id=self.id,
            valida_a_partir=self.valida_a_partir,
            valida_ate=self.valida_ate,
            criada_por=self.criada_por,
            criada_em=self.criada_em,
            alterada_por=alterado_por,
            alterada_em=_agora(),
            reason=self.reason,
            audit_reference=self.audit_reference,
            explanation=self.explanation,
            confidence_threshold=self.confidence_threshold,
        )

        # Aplica campos alterados
        for campo, valor in campos_alterados.items():
            if hasattr(nova, campo):
                setattr(nova, campo, valor)

        nova.reason = motivo_alteracao or nova.reason

        return nova

    def desativar(self, desativado_por: str, motivo: str) -> None:
        """
        Desativa a regra sem deletá-la.
        O histórico de lançamentos classificados por esta regra permanece.
        """
        self.ativa = False
        self.alterada_por = desativado_por
        self.alterada_em = _agora()
        if motivo:
            self.reason = f"[DESATIVADA] {motivo}"
