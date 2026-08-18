"""contas_contabeis + splits.empresa_id (DT-CC-01 / ADR 011, B.2.1)

Primeira etapa da sequência B.2 (FK composta) aprovada em ADR 011:
cadastro apenas, sem FK ainda ativa.

- Cria a tabela contas_contabeis, mesmo padrão de centros_custo
  (unicidade por empresa_id + codigo, não um id semântico).
- Adiciona splits.empresa_id, nullable nesta etapa — denormalizado de
  lancamentos.empresa_id, necessário para a FK composta
  (empresa_id, conta_codigo) -> contas_contabeis(empresa_id, codigo)
  que será ativada em B.2.4, depois de backfill (B.2.2) e cadastro das
  contas já em uso (B.2.3).

Nenhuma FK é criada aqui. Nenhum dado existente é alterado (backfill é
B.2.2). splits.conta_codigo permanece sem qualquer constraint adicional
nesta etapa.

Revision ID: f2b8d5e3a1c7
Revises: e1a9c4f0b7d2
Create Date: 2026-08-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2b8d5e3a1c7'
down_revision: Union[str, None] = 'e1a9c4f0b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contas_contabeis',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('codigo', sa.String(length=20), nullable=False),
        sa.Column('nome', sa.String(length=200), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('natureza', sa.String(length=10), nullable=False),
        sa.Column('guid_gnucash', sa.String(length=36), nullable=True),
        sa.Column('permite_lancamento', sa.Boolean(), nullable=False),
        sa.Column('centro_custo_obrigatorio', sa.Boolean(), nullable=False),
        sa.Column('conta_pai_id', sa.String(length=36), nullable=True),
        sa.Column('versao', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'codigo', name='uq_conta_contabil_empresa_codigo'),
    )
    op.create_index(
        op.f('ix_contas_contabeis_empresa_id'), 'contas_contabeis', ['empresa_id'],
    )

    op.add_column(
        'splits',
        sa.Column('empresa_id', sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f('ix_splits_empresa_id'), 'splits', ['empresa_id'],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_splits_empresa_id'), table_name='splits')
    op.drop_column('splits', 'empresa_id')

    op.drop_index(op.f('ix_contas_contabeis_empresa_id'), table_name='contas_contabeis')
    op.drop_table('contas_contabeis')
