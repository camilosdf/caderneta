"""HistoricoRepository — Etapa 7.3.

Recupera lançamentos aprovados e os transforma em CandidatoHistorico
para indexação no EmbeddingsPlugin.

Responsabilidade única: saber como extrair do banco os dados relevantes
para classificação semântica. Não sabe nada sobre embeddings, modelos
ou similaridade — apenas fornece os candidatos no formato esperado.

Localização: ai/ porque depende de ai.embeddings (CandidatoHistorico).
  A direção é ai/ → core/infra (permitida) — não o inverso.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.embeddings.embeddings_plugin import CandidatoHistorico
from core.domain.entities import StatusLancamento
from core.infra.db.models import LancamentoORM, SplitORM


class HistoricoRepository:
    """Acessa lançamentos aprovados para construir a base de candidatos.

    Usa SQLAlchemy diretamente (não passa por LancamentoRepository) para
    evitar carregar entidades de domínio completas — precisamos apenas das
    colunas relevantes para embedding (descricao, categoria, contas), sem
    os splits completos de cada lançamento.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def obter_candidatos(
        self,
        empresa_id: UUID,
        limit: int = 500,
        min_valor: float | None = None,
    ) -> list[CandidatoHistorico]:
        """Retorna candidatos a partir de lançamentos aprovados da empresa.

        Filtra por:
        - status APROVADO (excluindo rejeitados, rascunhos, pendentes)
        - empresa_id — nunca vaza dados entre empresas
        - limit — evita carregar histórico excessivo de uma vez

        Args:
            empresa_id: identificador da empresa — isolamento obrigatório.
            limit: máximo de candidatos retornados (mais recentes primeiro).
            min_valor: filtra lançamentos acima de um valor mínimo — útil
                       para não indexar micro-transações irrelevantes.
        """
        stmt = (
            select(LancamentoORM)
            .where(
                LancamentoORM.empresa_id == str(empresa_id),
                LancamentoORM.status == StatusLancamento.APROVADO.value,
                LancamentoORM.descricao.isnot(None),
            )
            .order_by(LancamentoORM.data_lancamento.desc())
            .limit(limit)
        )

        candidatos = []
        for lanc_orm in self._session.execute(stmt).scalars():
            conta_debito, conta_credito = self._extrair_contas(lanc_orm.id)
            if not (conta_debito and conta_credito):
                continue

            candidatos.append(CandidatoHistorico(
                descricao=lanc_orm.descricao or "",
                categoria=lanc_orm.categoria or "",
                conta_debito=conta_debito,
                conta_credito=conta_credito,
            ))

        return candidatos

    def _extrair_contas(self, lancamento_id: str) -> tuple[str, str]:
        """Extrai conta de débito e crédito dos splits do lançamento."""
        stmt = select(SplitORM).where(SplitORM.lancamento_id == lancamento_id)
        splits = list(self._session.execute(stmt).scalars())

        debito = next(
            (s.conta_codigo for s in splits if s.natureza == "debito"), ""
        )
        credito = next(
            (s.conta_codigo for s in splits if s.natureza == "credito"), ""
        )
        return debito, credito
