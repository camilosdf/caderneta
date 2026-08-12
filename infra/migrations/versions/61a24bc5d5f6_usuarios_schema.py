"""usuarios: schema pendente (mesma classe de debito que B2)

Materializa exclusivamente o schema ja declarado por UsuarioORM
(core/infra/db/models.py) -- ADR 008. A tabela existia apenas via
Base.metadata.create_all() em testes -- nunca havia sido migrada via
Alembic, tornando-a inexistente em qualquer ambiente PostgreSQL real
que so rode `alembic upgrade head`. Mesma classe de bloqueador ja
resolvida para transacoes_bancarias (B2, revision 7ee711d3c682).

Unidade tecnica autorizada isoladamente (Deliberacao Pos-Fase 6) --
fora da deliberacao de merito do Gate 0 (D1-D7 continuam pendentes,
nao resolvidos nem contornados por esta migration).

`alembic revision --autogenerate` foi usado apenas como mecanismo
auxiliar de conferencia (confirmou exatamente os mesmos campos abaixo)
-- o conteudo final foi escrito e revisado manualmente, nao aceito por
autoridade do autogenerate. Nenhuma alteracao em UsuarioORM,
repositories, API ou dominio integra este escopo.

Revision ID: 61a24bc5d5f6
Revises: 4f326ce831dc
Create Date: 2026-08-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '61a24bc5d5f6'
down_revision: Union[str, None] = '4f326ce831dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('usuarios',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('empresa_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('papel', sa.String(length=20), nullable=False),
    sa.Column('senha_hash', sa.String(length=255), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('current_authentication_id', sa.String(length=36), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usuarios_email'), 'usuarios', ['email'], unique=True)
    op.create_index(op.f('ix_usuarios_empresa_id'), 'usuarios', ['empresa_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usuarios_empresa_id'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_email'), table_name='usuarios')
    op.drop_table('usuarios')
