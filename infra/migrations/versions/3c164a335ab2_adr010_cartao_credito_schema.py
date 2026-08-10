"""adr010: cartao de credito - schema (cartoes_credito, faturas_cartao, compras_cartao)

DT-CC-01: CartaoCreditoORM.conta_codigo eh referencia textual, sem FK,
seguindo o padrao ja existente em splits.conta_codigo. Nao ha tabela
contas_contabeis nem ContaContabilORM neste projeto — fora de escopo
do ADR 010 (ver ADR 010, Secao "Debito tecnico registrado — DT-CC-01").

Revision ID: 3c164a335ab2
Revises: f43b99e177a7
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3c164a335ab2'
down_revision: Union[str, None] = 'f43b99e177a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cartoes_credito',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('emissor', sa.String(length=50), nullable=False),
    sa.Column('final_numero', sa.String(length=4), nullable=False),
    sa.Column('titular', sa.String(length=200), nullable=False),
    sa.Column('conta_codigo', sa.String(length=20), nullable=False),
    sa.Column('guid_gnucash', sa.String(length=36), nullable=True),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'emissor', 'final_numero', 'titular',
                         name='uq_cartao_credito_identidade')
    )
    op.create_index(op.f('ix_cartoes_credito_empresa_id'), 'cartoes_credito', ['empresa_id'], unique=False)

    op.create_table('faturas_cartao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('cartao_id', sa.String(length=36), nullable=False),
    sa.Column('documento_id', sa.String(length=36), nullable=True),
    sa.Column('periodo_referencia', sa.Date(), nullable=False),
    sa.Column('data_fechamento', sa.Date(), nullable=True),
    sa.Column('data_vencimento', sa.Date(), nullable=True),
    sa.Column('valor_total_declarado', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('status_fechamento', sa.String(length=20), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cartao_id'], ['cartoes_credito.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['documento_id'], ['documentos.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cartao_id', 'periodo_referencia', name='uq_fatura_cartao_periodo')
    )
    op.create_index(op.f('ix_faturas_cartao_cartao_id'), 'faturas_cartao', ['cartao_id'], unique=False)
    op.create_index(op.f('ix_faturas_cartao_documento_id'), 'faturas_cartao', ['documento_id'], unique=False)
    op.create_index(op.f('ix_faturas_cartao_empresa_id'), 'faturas_cartao', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_faturas_cartao_periodo_referencia'), 'faturas_cartao', ['periodo_referencia'], unique=False)

    op.create_table('compras_cartao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('fatura_id', sa.String(length=36), nullable=False),
    sa.Column('lancamento_id', sa.String(length=36), nullable=True),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('estabelecimento', sa.String(length=300), nullable=True),
    sa.Column('descricao_original', sa.String(length=500), nullable=True),
    sa.Column('data_compra', sa.Date(), nullable=True),
    sa.Column('valor', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('parcela_atual', sa.Integer(), nullable=True),
    sa.Column('total_parcelas', sa.Integer(), nullable=True),
    sa.Column('posicao_linha', sa.Integer(), nullable=False),
    sa.Column('hash_linha', sa.String(length=64), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fatura_id'], ['faturas_cartao.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lancamento_id'], ['lancamentos.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fatura_id', 'posicao_linha', name='uq_compra_cartao_posicao')
    )
    op.create_index(op.f('ix_compras_cartao_empresa_id'), 'compras_cartao', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_compras_cartao_fatura_id'), 'compras_cartao', ['fatura_id'], unique=False)
    op.create_index(op.f('ix_compras_cartao_lancamento_id'), 'compras_cartao', ['lancamento_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_compras_cartao_lancamento_id'), table_name='compras_cartao')
    op.drop_index(op.f('ix_compras_cartao_fatura_id'), table_name='compras_cartao')
    op.drop_index(op.f('ix_compras_cartao_empresa_id'), table_name='compras_cartao')
    op.drop_table('compras_cartao')

    op.drop_index(op.f('ix_faturas_cartao_periodo_referencia'), table_name='faturas_cartao')
    op.drop_index(op.f('ix_faturas_cartao_empresa_id'), table_name='faturas_cartao')
    op.drop_index(op.f('ix_faturas_cartao_documento_id'), table_name='faturas_cartao')
    op.drop_index(op.f('ix_faturas_cartao_cartao_id'), table_name='faturas_cartao')
    op.drop_table('faturas_cartao')

    op.drop_index(op.f('ix_cartoes_credito_empresa_id'), table_name='cartoes_credito')
    op.drop_table('cartoes_credito')
