"""compras_cartao.confidence_valor/confidence_campo (DT-CC-02, ADR 010)

Persiste core.domain.entities.ConfidenceScore em CompraCartao, hoje
descartado no round-trip ORM->domínio (_item_para_dominio hardcodeava
confidence=None). LancamentoService.construir_lancamento_compra_cartao
já propaga corretamente compra.confidence para Lancamento.confidence
(D7) — o elo quebrado era só persistência, não o fluxo B6-0.

Duas colunas, não uma: ConfidenceScore carrega valor (float, 0.0-1.0)
E campo (a qual campo da extração o score se refere) — uma coluna
única perderia essa segunda informação.

Revision ID: e1a9c4f0b7d2
Revises: 8e2c4f1a9b3d
Create Date: 2026-08-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a9c4f0b7d2'
down_revision: Union[str, None] = '8e2c4f1a9b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'compras_cartao',
        sa.Column('confidence_valor', sa.Float(), nullable=True),
    )
    op.add_column(
        'compras_cartao',
        sa.Column('confidence_campo', sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('compras_cartao', 'confidence_campo')
    op.drop_column('compras_cartao', 'confidence_valor')
