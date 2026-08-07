"""Alembic env.py — configuração do ambiente de migrations.

Lê DATABASE_URL da variável de ambiente (ou do alembic.ini como fallback).
Importa Base de core.infra.db para que autogenerate detecte os modelos ORM.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importa Base — todos os modelos ORM precisam estar importados aqui
# para que o autogenerate funcione corretamente
from core.infra.db.session import Base  # noqa: F401

# Importar modelos para registrá-los na Base
from core.infra.db.models import (  # noqa: F401
    AuditEventoORM,
    DocumentoORM,
    LancamentoORM,
    PeriodoContabilORM,
    SplitORM,
)

config = context.config

# Sobrescrever sqlalchemy.url com variável de ambiente se disponível
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migrations sem conexão real — gera SQL puro."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Migrations com conexão real ao banco."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
