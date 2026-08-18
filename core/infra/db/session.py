"""Infraestrutura de banco de dados — SQLAlchemy 2.

Responsabilidades:
- Base declarativa compartilhada por todos os modelos ORM
- SessionFactory: cria sessões configuradas por ambiente
- get_session(): context manager para uso em repositórios

Configuração via variáveis de ambiente:
    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/caderneta

Para testes, aceita SQLite em memória:
    DATABASE_URL=sqlite+aiosqlite:///:memory:
    DATABASE_URL=sqlite:///caderneta_test.db
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa compartilhada por todos os modelos ORM do Caderneta."""
    pass


class SessionFactory:
    """Fábrica de sessões SQLAlchemy 2.

    Uso:
        factory = SessionFactory("postgresql+psycopg://...")
        with factory.session() as session:
            session.add(obj)
            session.commit()
    """

    def __init__(
        self,
        url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        enforce_foreign_keys: bool = False,
    ) -> None:
        """
        enforce_foreign_keys (DT-CC-01 / ADR 011, B.2.4): ativa
        `PRAGMA foreign_keys=ON` por conexão, apenas para SQLite —
        SQLite não aplica FK por padrão (achado da auditoria prévia a
        B.2.4: `test_processar_fatura_cartao_fase4.py`, achado 1).
        PostgreSQL sempre aplica FK nativamente, com ou sem esta flag —
        aqui ela é no-op para esse dialeto.

        Default False para preservar o comportamento da suíte de
        testes hermética, que constrói lançamentos/splits com códigos
        de conta arbitrários não cadastrados em `contas_contabeis` —
        ativar globalmente quebra ~126 testes fora do domínio de
        DT-CC-01 (ver Fase 1 do Plano B.2.4). True apenas nos dois
        bootstraps de execução real (`session_factory_from_env()` e
        `core/cli.py::_session_factory()`) e no fixture do guardrail
        de schema migrado.

        Esta flag é uma adaptação de enforcement para SQLite, não um
        mecanismo de segurança contábil equivalente à FK do
        PostgreSQL. O contrato de integridade definitivo é o schema
        migrado (Alembic) — `enforce_foreign_keys=False` nunca deve
        ser interpretado como autorização para produção sem
        integridade referencial.
        """
        # SQLite não suporta pool_size/max_overflow
        connect_args: dict = {}
        engine_kwargs: dict = {"echo": echo}

        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        else:
            engine_kwargs["pool_size"] = pool_size
            engine_kwargs["max_overflow"] = max_overflow

        self._engine = create_engine(
            url,
            connect_args=connect_args,
            **engine_kwargs,
        )

        if enforce_foreign_keys and url.startswith("sqlite"):
            @event.listens_for(self._engine, "connect")
            def _ativar_fk_sqlite(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=True,
            expire_on_commit=False,
        )

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager que garante commit/rollback e fechamento."""
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def criar_tabelas(self) -> None:
        """Cria todas as tabelas registradas na Base. Usado em testes."""
        Base.metadata.create_all(self._engine)

    def remover_tabelas(self) -> None:
        """Remove todas as tabelas. Usado em testes."""
        Base.metadata.drop_all(self._engine)

    def verificar_conexao(self) -> bool:
        """Verifica se o banco está acessível."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    @property
    def engine(self):
        return self._engine


def session_factory_from_env() -> Optional[SessionFactory]:
    """Cria SessionFactory a partir da variável DATABASE_URL.

    Retorna None se DATABASE_URL não estiver definida.

    Bootstrap de execução real (usada por api/main.py e
    api/dependencies.py) — enforce_foreign_keys=True (DT-CC-01 / ADR
    011, B.2.4): ver docstring de SessionFactory.__init__.
    """
    import os
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return SessionFactory(url, enforce_foreign_keys=True)
