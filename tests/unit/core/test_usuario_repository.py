"""Testes do UsuarioRepository.

Cobre: criar, salvar, buscar por id/email, listar por empresa,
obter_hash_senha (hash tratado como dado opaco, nunca interpretado
pelo repositório), unicidade de e-mail.
"""

from uuid import uuid4

import pytest

from core.domain.entities import Usuario
from core.infra.db import SessionFactory
from core.infra.repositories import UsuarioRepository
from core.infra.repositories.usuario_repository import EmailJaCadastradoError


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


def _usuario(email="teste@caderneta.com", papel="operador", empresa_id=None) -> Usuario:
    return Usuario(
        empresa_id=empresa_id or uuid4(),
        email=email,
        nome="Usuário Teste",
        papel=papel,
    )


class TestUsuarioRepository:
    def test_criar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        usuario = _usuario()
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="hash-fake-123")

        with sf.session() as session:
            encontrado = UsuarioRepository(session).buscar_por_id(usuario.id)
            assert encontrado is not None
            assert encontrado.email == "teste@caderneta.com"
            assert encontrado.papel == "operador"

    def test_buscar_por_email(self, sf: SessionFactory) -> None:
        usuario = _usuario(email="contador@caderneta.com")
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="hash-fake")

        with sf.session() as session:
            encontrado = UsuarioRepository(session).buscar_por_email("contador@caderneta.com")
            assert encontrado is not None
            assert encontrado.id == usuario.id

    def test_buscar_email_inexistente_retorna_none(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            assert UsuarioRepository(session).buscar_por_email("nao@existe.com") is None

    def test_criar_email_duplicado_lanca_erro(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            UsuarioRepository(session).criar(
                _usuario(email="dup@caderneta.com"), senha_hash="hash1"
            )

        with pytest.raises(EmailJaCadastradoError):
            with sf.session() as session:
                UsuarioRepository(session).criar(
                    _usuario(email="dup@caderneta.com"), senha_hash="hash2"
                )

    def test_obter_hash_senha(self, sf: SessionFactory) -> None:
        usuario = _usuario(email="hash@caderneta.com")
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="$argon2id$fake$hash")

        with sf.session() as session:
            h = UsuarioRepository(session).obter_hash_senha("hash@caderneta.com")
            assert h == "$argon2id$fake$hash"

    def test_obter_hash_senha_usuario_inexistente(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            assert UsuarioRepository(session).obter_hash_senha("nao@existe.com") is None

    def test_domain_usuario_nao_expoe_hash(self, sf: SessionFactory) -> None:
        """Usuario (domínio) nunca deve carregar senha_hash — só UsuarioORM."""
        usuario = _usuario()
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="hash-secreto")

        with sf.session() as session:
            encontrado = UsuarioRepository(session).buscar_por_id(usuario.id)
            assert not hasattr(encontrado, "senha_hash")

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = UsuarioRepository(session)
            repo.criar(_usuario(email="a@x.com", empresa_id=empresa_id), senha_hash="h1")
            repo.criar(_usuario(email="b@x.com", empresa_id=empresa_id), senha_hash="h2")
            repo.criar(_usuario(email="c@x.com"), senha_hash="h3")  # outra empresa

        with sf.session() as session:
            lista = UsuarioRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_listar_apenas_ativos(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = UsuarioRepository(session)
            repo.criar(_usuario(email="ativo@x.com", empresa_id=empresa_id), senha_hash="h1")
            inativo = _usuario(email="inativo@x.com", empresa_id=empresa_id)
            inativo.ativo = False
            repo.criar(inativo, senha_hash="h2")

        with sf.session() as session:
            ativos = UsuarioRepository(session).listar_por_empresa(
                empresa_id, apenas_ativos=True
            )
            assert len(ativos) == 1
            assert ativos[0].email == "ativo@x.com"

    def test_salvar_atualiza_sem_alterar_hash(self, sf: SessionFactory) -> None:
        usuario = _usuario(email="update@x.com")
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="hash-original")

        with sf.session() as session:
            repo = UsuarioRepository(session)
            u = repo.buscar_por_id(usuario.id)
            u.nome = "Nome Atualizado"
            repo.salvar(u)  # sem passar senha_hash

        with sf.session() as session:
            repo = UsuarioRepository(session)
            u = repo.buscar_por_id(usuario.id)
            assert u.nome == "Nome Atualizado"
            assert repo.obter_hash_senha("update@x.com") == "hash-original"

    def test_salvar_pode_atualizar_hash(self, sf: SessionFactory) -> None:
        usuario = _usuario(email="rehash@x.com")
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="hash-antigo")

        with sf.session() as session:
            repo = UsuarioRepository(session)
            u = repo.buscar_por_id(usuario.id)
            repo.salvar(u, senha_hash="hash-novo")

        with sf.session() as session:
            assert UsuarioRepository(session).obter_hash_senha("rehash@x.com") == "hash-novo"

    def test_papel_preservado(self, sf: SessionFactory) -> None:
        usuario = _usuario(email="supervisor@x.com", papel="supervisor")
        with sf.session() as session:
            UsuarioRepository(session).criar(usuario, senha_hash="h")

        with sf.session() as session:
            encontrado = UsuarioRepository(session).buscar_por_email("supervisor@x.com")
            assert encontrado.papel == "supervisor"
            assert encontrado.pode_aprovar_alto_valor() is True
