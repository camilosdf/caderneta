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

from sqlalchemy import create_engine, text
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
    ) -> None:
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
    """
    import os
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return SessionFactory(url)
