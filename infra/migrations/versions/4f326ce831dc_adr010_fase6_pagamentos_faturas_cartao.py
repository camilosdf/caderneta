"""adr010 fase6: pagamentos_faturas_cartao (B6-5, B6-6, B6-14)

Materializa o vinculo Fatura <-> Lancamento de pagamento <-> Transacao
bancaria, com as tres FKs reais (possivel somente apos B2 resolver a
ausencia de migration de transacoes_bancarias). As tres UNIQUE isoladas
materializam em banco a restricao 1:1 ja comprovada em memoria por B6-4.

Nao altera nenhuma tabela existente. Nao toca Lancamento/LancamentoORM.

Revision ID: 4f326ce831dc
Revises: 7ee711d3c682
Create Date: 2026-08-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '4f326ce831dc'
down_revision: Union[str, None] = '7ee711d3c682'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pagamentos_faturas_cartao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('fatura_cartao_id', sa.String(length=36), nullable=False),
    sa.Column('lancamento_id', sa.String(length=36), nullable=False),
    sa.Column('transacao_bancaria_id', sa.String(length=36), nullable=False),
    sa.Column('metodo_matching', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fatura_cartao_id'], ['faturas_cartao.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lancamento_id'], ['lancamentos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['transacao_bancaria_id'], ['transacoes_bancarias.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fatura_cartao_id', name='uq_pagamento_fatura_cartao'),
    sa.UniqueConstraint('lancamento_id', name='uq_pagamento_lancamento'),
    sa.UniqueConstraint('transacao_bancaria_id', name='uq_pagamento_transacao_bancaria')
    )
    op.create_index(op.f('ix_pagamentos_faturas_cartao_empresa_id'), 'pagamentos_faturas_cartao', ['empresa_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pagamentos_faturas_cartao_empresa_id'), table_name='pagamentos_faturas_cartao')
    op.drop_table('pagamentos_faturas_cartao')
