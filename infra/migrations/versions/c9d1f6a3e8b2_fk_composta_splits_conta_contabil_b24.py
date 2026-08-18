"""FK composta splits -> contas_contabeis + NOT NULL (DT-CC-01 / ADR 011, B.2.4)

Quarta e última etapa da sequência B.2 aprovada em ADR 011. Ativa o
contrato de integridade final:

- splits.empresa_id passa a NOT NULL (já era preenchido por todo
  código novo desde B.2.2, e retroativamente por essa mesma migration
  de dados; esta migration pressupõe que a4c7f19e2b6d já rodou).
- FK composta (empresa_id, conta_codigo) -> contas_contabeis
  (empresa_id, codigo), satisfeita pela UniqueConstraint criada em
  f2b8d5e3a1c7 (B.2.1).

Migration defensiva (SRE/QA — Fase 1/2 do Plano B.2.4): antes de
alterar o schema, valida explicitamente a ausência de órfãos —
splits.empresa_id NULL (backfill incompleto) ou conta_codigo sem
cadastro correspondente (cadastro incompleto). Aborta com erro claro
em vez de aplicar um schema parcialmente íntegro.

Enforcement real em runtime depende de SessionFactory(
enforce_foreign_keys=True) no SQLite (core/infra/db/session.py) — no
PostgreSQL a FK é sempre aplicada nativamente, com ou sem essa flag.
A suíte de testes hermética não ativa a flag (ver Fase 1 do Plano: o
experimento controlado mediu 126 falhas em 20 arquivos fora do escopo
de DT-CC-01 ao forçar o enforcement globalmente) — isso não afeta o
schema em si, apenas se ele é checado em runtime por SQLite.

cartoes_credito.conta_codigo permanece fora do escopo desta FK (achado
da Fase 1 do Plano B.2.4, já documentado em models.py como "referência
textual, sem FK").

batch_alter_table é necessário no SQLite (recria a tabela) para
ALTER COLUMN + ADD CONSTRAINT em tabela já existente; no PostgreSQL o
Alembic executa ALTER TABLE diretamente sob o mesmo batch_alter_table,
sem recriação.

Revision ID: c9d1f6a3e8b2
Revises: b7e4a2c9f1d3
Create Date: 2026-08-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d1f6a3e8b2'
down_revision: Union[str, None] = 'b7e4a2c9f1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    orfaos_null = conn.execute(sa.text(
        "SELECT COUNT(*) FROM splits WHERE empresa_id IS NULL"
    )).scalar_one()
    if orfaos_null:
        raise RuntimeError(
            f"B.2.4 abortada: {orfaos_null} splits com empresa_id NULL — "
            "backfill (a4c7f19e2b6d) incompleto. Não é seguro tornar a "
            "coluna NOT NULL nesse estado."
        )

    orfaos_fk = conn.execute(sa.text(
        "SELECT COUNT(*) FROM splits s "
        "LEFT JOIN contas_contabeis c "
        "  ON c.empresa_id = s.empresa_id AND c.codigo = s.conta_codigo "
        "WHERE c.id IS NULL"
    )).scalar_one()
    if orfaos_fk:
        raise RuntimeError(
            f"B.2.4 abortada: {orfaos_fk} splits referenciam conta_codigo "
            "não cadastrado em contas_contabeis — cadastro (b7e4a2c9f1d3) "
            "incompleto. Não é seguro ativar a FK composta nesse estado."
        )

    with op.batch_alter_table("splits") as batch_op:
        batch_op.alter_column(
            "empresa_id", existing_type=sa.String(length=36), nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_splits_conta_contabil",
            "contas_contabeis",
            ["empresa_id", "conta_codigo"],
            ["empresa_id", "codigo"],
        )


def downgrade() -> None:
    with op.batch_alter_table("splits") as batch_op:
        batch_op.drop_constraint("fk_splits_conta_contabil", type_="foreignkey")
        batch_op.alter_column(
            "empresa_id", existing_type=sa.String(length=36), nullable=True,
        )
