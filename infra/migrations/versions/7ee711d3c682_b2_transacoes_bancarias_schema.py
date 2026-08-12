"""b2: transacoes_bancarias - schema pendente (bloqueador Gate 0)

Materializa exclusivamente o schema já declarado por TransacaoBancariaORM
(core/infra/db/models.py). A tabela existia apenas via Base.metadata.create_all()
em testes -- nunca havia sido migrada via Alembic, o que a torna inexistente
em qualquer ambiente PostgreSQL real que só rode `alembic upgrade head`.

Registrado como BLOQUEADOR na pauta de deliberação do Gate 0 (item B2).
Resolvido aqui como pré-requisito independente da Fase 6/ADR 010 --
nenhuma alteração de domínio, cartão ou teste pytest integra este escopo.

`alembic revision --autogenerate` foi usado apenas como mecanismo auxiliar
de conferência (confirmou exatamente os mesmos campos abaixo) -- o
conteúdo final foi escrito e revisado manualmente, não aceito por
autoridade do autogenerate. O autogenerate também detectou a tabela
`usuarios` na mesma situação (sem migration); fica registrada como
achado de governança análogo, fora do escopo desta migration.

Revision ID: 7ee711d3c682
Revises: 3c164a335ab2
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7ee711d3c682'
down_revision: Union[str, None] = '3c164a335ab2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('transacoes_bancarias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('instituicao', sa.String(length=20), nullable=False),
    sa.Column('agencia', sa.String(length=20), nullable=False),
    sa.Column('numero_conta', sa.String(length=50), nullable=False),
    sa.Column('tipo_conta', sa.String(length=20), nullable=False),
    sa.Column('fitid', sa.String(length=100), nullable=False),
    sa.Column('data', sa.Date(), nullable=False),
    sa.Column('valor', sa.String(length=20), nullable=False),
    sa.Column('natureza', sa.String(length=10), nullable=False),
    sa.Column('descricao', sa.String(length=500), nullable=False),
    sa.Column('referencia', sa.String(length=100), nullable=False),
    sa.Column('origem', sa.String(length=20), nullable=False),
    sa.Column('id_importacao', sa.String(length=36), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instituicao', 'numero_conta', 'fitid',
                         name='uq_transacao_bancaria_fitid')
    )
    op.create_index(op.f('ix_transacoes_bancarias_empresa_id'), 'transacoes_bancarias', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_transacoes_bancarias_data'), 'transacoes_bancarias', ['data'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transacoes_bancarias_data'), table_name='transacoes_bancarias')
    op.drop_index(op.f('ix_transacoes_bancarias_empresa_id'), table_name='transacoes_bancarias')
    op.drop_table('transacoes_bancarias')
