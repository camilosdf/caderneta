"""cadastro retroativo de contas já em uso (DT-CC-01 / ADR 011, B.2.3)

Terceira etapa da sequência B.2. Descobre empiricamente todo par
(empresa_id, conta_codigo) já persistido em splits e cartoes_credito
que ainda não tem cadastro em contas_contabeis, e cria um registro
placeholder para cada um — nunca como se fosse uma conta já revisada e
correta. Pré-requisito para B.2.4 (NOT NULL + FK composta): sem isso,
ativar a FK quebraria imediatamente qualquer lançamento já persistido
cuja conta não estivesse cadastrada.

Registrado explicitamente (ver ADR 011, B.2.3): esta migration cobre
só o que JÁ FOI usado e persistido. Não cobre proativamente os 8
códigos hardcoded do motor tributário (core/rule_engine/tax_engine.py,
CONTAS_TRIBUTARIAS_PADRAO) para empresas que ainda não os usaram — esse
dict não é por empresa, não há como inferir de antemão quais empresas
vão precisar de quais desses códigos. Fica como risco residual
conhecido para B.2.4: a primeira vez que uma empresa gerar um
lançamento tributário terá que ou já ter cadastrado a conta via
`caderneta conta criar` (comando novo desta mesma unidade), ou o
lançamento falhará contra a FK.

IDs gerados em Python (uuid4), não em SQL — portátil entre SQLite e
PostgreSQL, sem depender de gen_random_uuid()/uuid_generate_v4()
(extensão nem sempre habilitada).

Revision ID: b7e4a2c9f1d3
Revises: a4c7f19e2b6d
Create Date: 2026-08-18 00:00:00.000000
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e4a2c9f1d3'
down_revision: Union[str, None] = 'a4c7f19e2b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME_PLACEHOLDER = "(pendente de revisão — cadastrada automaticamente por B.2.3)"

_contas_contabeis = sa.table(
    'contas_contabeis',
    sa.column('id', sa.String),
    sa.column('empresa_id', sa.String),
    sa.column('codigo', sa.String),
    sa.column('nome', sa.String),
    sa.column('tipo', sa.String),
    sa.column('natureza', sa.String),
    sa.column('guid_gnucash', sa.String),
    sa.column('permite_lancamento', sa.Boolean),
    sa.column('centro_custo_obrigatorio', sa.Boolean),
    sa.column('conta_pai_id', sa.String),
    sa.column('versao', sa.Integer),
)


def upgrade() -> None:
    conn = op.get_bind()

    ja_cadastradas = {
        (row.empresa_id, row.codigo)
        for row in conn.execute(sa.text("SELECT empresa_id, codigo FROM contas_contabeis"))
    }

    em_uso: set[tuple[str, str]] = set()
    for row in conn.execute(sa.text(
        "SELECT DISTINCT empresa_id, conta_codigo FROM splits WHERE empresa_id IS NOT NULL"
    )):
        em_uso.add((row.empresa_id, row.conta_codigo))
    for row in conn.execute(sa.text(
        "SELECT DISTINCT empresa_id, conta_codigo FROM cartoes_credito"
    )):
        em_uso.add((row.empresa_id, row.conta_codigo))

    faltantes = sorted(em_uso - ja_cadastradas)
    if not faltantes:
        return

    conn.execute(
        _contas_contabeis.insert(),
        [
            {
                "id": str(uuid.uuid4()),
                "empresa_id": empresa_id,
                "codigo": codigo,
                "nome": _NOME_PLACEHOLDER,
                "tipo": "",
                "natureza": "debito",
                "guid_gnucash": None,
                "permite_lancamento": True,
                "centro_custo_obrigatorio": False,
                "conta_pai_id": None,
                "versao": 1,
            }
            for (empresa_id, codigo) in faltantes
        ],
    )


def downgrade() -> None:
    # Reversível com segurança: remove só as linhas com o marcador
    # exclusivo desta migration — nunca cadastros feitos manualmente
    # depois (via `caderneta conta criar`) nem os já existentes antes.
    op.execute(
        sa.text("DELETE FROM contas_contabeis WHERE nome = :nome").bindparams(
            nome=_NOME_PLACEHOLDER
        )
    )
