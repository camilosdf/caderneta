"""Testes da infraestrutura de banco de dados — A1.

Cobre: SessionFactory, Base ORM, verificar_conexao, criar/remover tabelas.
Usa SQLite em memória — sem dependência de PostgreSQL nos testes unitários.
"""

import pytest
from sqlalchemy import Column, Integer, String, inspect, text

from core.infra.db.session import Base, SessionFactory, session_factory_from_env


# =============================================================
# MODELO DE TESTE — só para este arquivo
# =============================================================

class ModeloTeste(Base):
    __tablename__ = "teste_a1"
    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)


# =============================================================
# FIXTURES
# =============================================================

@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


# =============================================================
# SessionFactory
# =============================================================

class TestSessionFactory:
    def test_cria_com_sqlite(self) -> None:
        sf = SessionFactory("sqlite:///:memory:")
        assert sf is not None

    def test_verifica_conexao(self, sf: SessionFactory) -> None:
        assert sf.verificar_conexao() is True

    def test_conexao_invalida_retorna_false(self) -> None:
        # SQLite com path inválido de fato falha na execução
        sf = SessionFactory("sqlite:////\x00/invalido")
        assert sf.verificar_conexao() is False

    def test_session_context_manager(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_session_commit_automatico(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            session.add(ModeloTeste(nome="Teste A1"))

        with sf.session() as session:
            obj = session.query(ModeloTeste).filter_by(nome="Teste A1").first()
            assert obj is not None
            assert obj.nome == "Teste A1"

    def test_session_rollback_em_excecao(self, sf: SessionFactory) -> None:
        with pytest.raises(ValueError):
            with sf.session() as session:
                session.add(ModeloTeste(nome="Vai ser revertido"))
                raise ValueError("erro simulado")

        with sf.session() as session:
            count = session.query(ModeloTeste).filter_by(nome="Vai ser revertido").count()
            assert count == 0

    def test_expire_on_commit_false(self, sf: SessionFactory) -> None:
        """Objetos acessíveis após commit sem nova query."""
        with sf.session() as session:
            obj = ModeloTeste(nome="Expire test")
            session.add(obj)
            session.flush()
            obj_id = obj.id
        # Se expire_on_commit=True, acessar obj.nome aqui lançaria DetachedInstanceError
        assert obj.nome == "Expire test"
        assert obj.id == obj_id


# =============================================================
# Base ORM
# =============================================================

class TestBaseORM:
    def test_criar_tabelas(self) -> None:
        sf = SessionFactory("sqlite:///:memory:")
        sf.criar_tabelas()
        inspector = inspect(sf.engine)
        assert "teste_a1" in inspector.get_table_names()

    def test_remover_tabelas(self) -> None:
        sf = SessionFactory("sqlite:///:memory:")
        sf.criar_tabelas()
        sf.remover_tabelas()
        inspector = inspect(sf.engine)
        assert "teste_a1" not in inspector.get_table_names()

    def test_base_metadata_registra_modelo(self) -> None:
        assert "teste_a1" in Base.metadata.tables


# =============================================================
# session_factory_from_env
# =============================================================

class TestSessionFactoryFromEnv:
    def test_retorna_none_sem_env(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert session_factory_from_env() is None

    def test_retorna_factory_com_env(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        sf = session_factory_from_env()
        assert sf is not None
        assert sf.verificar_conexao() is True
