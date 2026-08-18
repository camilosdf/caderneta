"""backfill splits.empresa_id a partir de lancamentos (DT-CC-01 / ADR 011, B.2.2)

Segunda etapa da sequência B.2. splits.empresa_id foi adicionado
(nullable) em f2b8d5e3a1c7 mas nenhum Split existente até então tinha o
valor populado. Esta migration é de DADOS, não de schema: para todo
Split já persistido, copia empresa_id do Lancamento pai via subquery
correlacionada — portátil entre SQLite e PostgreSQL, sem depender de
UPDATE...FROM (não suportado por versões mais antigas de SQLite).

Daqui em diante, todo Split novo já chega com empresa_id preenchido
(core/infra/repositories/lancamento_repository.py, _split_para_orm,
alterado nesta mesma unidade B.2.2) — este backfill cobre só o que já
existia antes dessa mudança de código entrar em vigor.

A coluna splits.empresa_id permanece nullable após esta migration —
tornar NOT NULL e ativar a FK composta é B.2.4, depois de B.2.3
(cadastro das contas já em uso). Downgrade não reverte os dados
(zerar empresa_id perderia informação sem necessidade — a coluna em si
já foi criada nullable e será removida, se for o caso, apenas no
downgrade de f2b8d5e3a1c7).

Revision ID: a4c7f19e2b6d
Revises: f2b8d5e3a1c7
Create Date: 2026-08-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a4c7f19e2b6d'
down_revision: Union[str, None] = 'f2b8d5e3a1c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE splits
        SET empresa_id = (
            SELECT lancamentos.empresa_id
            FROM lancamentos
            WHERE lancamentos.id = splits.lancamento_id
        )
        WHERE splits.empresa_id IS NULL
        """
    )


def downgrade() -> None:
    # Migration de dados — downgrade é no-op deliberado. Zerar
    # empresa_id de volta para NULL não desfaz dano nenhum (a coluna
    # continua nullable) e destruiria informação sem necessidade
    # arquitetural. A remoção da própria coluna é responsabilidade do
    # downgrade de f2b8d5e3a1c7, não desta migration.
    pass
