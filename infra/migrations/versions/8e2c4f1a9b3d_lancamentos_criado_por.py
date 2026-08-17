"""lancamentos.criado_por (Gate 0 D1)

usuarios e transacoes_bancarias já existem nesta linha de commits
(61a24bc5d5f6_usuarios_schema.py e 7ee711d3c682_b2_transacoes_bancarias_schema.py,
resolvidos isoladamente pela Deliberação Pós-Fase 6) — esta migration
NÃO as recria. Escopo restrito à coluna de autoria de Lancamento (D1) e
ao backfill controlado correspondente.

Revision ID: 8e2c4f1a9b3d
Revises: 61a24bc5d5f6
Create Date: 2026-08-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8e2c4f1a9b3d'
down_revision: Union[str, None] = '61a24bc5d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lancamentos', sa.Column('criado_por', sa.String(length=100), nullable=True))

    # --- Gate 0 — D1: backfill controlado ---------------------------------
    # PolicyEngine.avaliar_aprovacao() passa a negar aprovação quando
    # criado_por é NULL (falha fechada — ver core/policies/engine.py,
    # política "origem_desconhecida"). Sem este backfill, todo lançamento
    # PENDENTE já existente na base ficaria travado, sem poder ser aprovado
    # nem rejeitado, a partir do deploy desta migration.
    #
    # Escopo deliberadamente restrito a status='pendente': são os únicos
    # registros que precisam permanecer acionáveis (aprovação/rejeição).
    # Lançamentos em outros status (aprovado, rejeitado, exportado,
    # rascunho) não passam por avaliar_aprovacao() novamente e não são
    # afetados pela falha fechada — não há necessidade de tocá-los aqui.
    #
    # Valor "origem:legado", não "pipeline:legado": não há, nesta migration,
    # evidência auditável e verificada de que 100% dos registros pré-D1
    # vieram do pipeline (mesmo sendo o único caminho de criação hoje
    # conhecido no código) — o valor não deve afirmar uma origem que não
    # foi confirmada contra os dados reais da base em produção.
    op.execute(
        sa.text(
            "UPDATE lancamentos SET criado_por = 'origem:legado' "
            "WHERE criado_por IS NULL AND status = 'pendente'"
        )
    )


def downgrade() -> None:
    op.drop_column('lancamentos', 'criado_por')
