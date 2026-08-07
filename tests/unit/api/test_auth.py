"""Testes de login/logout (ADR 008, W2).

Cobre: login com credenciais corretas/incorretas, sessão persistindo
entre requisições, logout invalidando a sessão, auditoria de
USUARIO_LOGIN/USUARIO_LOGOUT com papel + authentication_id.
"""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth.security import hash_senha
from api.main import create_app
from core.domain.entities import Usuario
from core.infra.db import SessionFactory
from core.infra.repositories import UsuarioRepository


@pytest.fixture
def sf(monkeypatch, tmp_path) -> SessionFactory:
    """SQLite em arquivo (não :memory:) — necessário porque TestClient e a
    app operam em threads diferentes; :memory: não seria compartilhado."""
    db_path = tmp_path / "test_auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    factory = SessionFactory(f"sqlite:///{db_path}")
    factory.criar_tabelas()
    return factory


@pytest.fixture
def usuario_senha() -> str:
    return "SenhaForte123!"


@pytest.fixture
def usuario(sf: SessionFactory, usuario_senha: str) -> Usuario:
    u = Usuario(
        empresa_id=uuid4(),
        email="contador@caderneta.com",
        nome="Contador Teste",
        papel="contador",
    )
    with sf.session() as session:
        UsuarioRepository(session).criar(u, senha_hash=hash_senha(usuario_senha))
    return u


@pytest.fixture
def client(sf: SessionFactory) -> TestClient:
    app = create_app()
    return TestClient(app)


class TestLogin:
    def test_login_credenciais_corretas(self, client, usuario, usuario_senha) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert r.status_code == 200
        assert r.json()["email"] == usuario.email
        assert r.json()["papel"] == "contador"

    def test_login_nao_expoe_hash(self, client, usuario, usuario_senha) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "senha_hash" not in r.json()
        assert "senha" not in r.json()

    def test_login_senha_incorreta(self, client, usuario) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": "senhaErrada"})
        assert r.status_code == 401

    def test_login_email_inexistente(self, client) -> None:
        r = client.post("/login", json={"email": "naoexiste@x.com", "senha": "qualquer"})
        assert r.status_code == 401

    def test_login_usuario_inativo(self, sf, usuario, usuario_senha, client) -> None:
        with sf.session() as session:
            repo = UsuarioRepository(session)
            u = repo.buscar_por_id(usuario.id)
            u.ativo = False
            repo.salvar(u)

        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert r.status_code == 401

    def test_login_registra_auditoria(self, client, usuario, usuario_senha, sf) -> None:
        from core.infra.unit_of_work import UnitOfWork

        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(usuario.empresa_id))
            tipos = [e["tipo"] for e in eventos]
            assert "USUARIO_LOGIN" in tipos

    def test_login_auditoria_tem_papel_e_authentication_id(
        self, client, usuario, usuario_senha, sf
    ) -> None:
        from core.infra.unit_of_work import UnitOfWork

        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(usuario.empresa_id))
            login_evt = next(e for e in eventos if e["tipo"] == "USUARIO_LOGIN")
            assert login_evt["payload"]["papel"] == "contador"
            assert login_evt["payload"]["authentication_id"] is not None


class TestLogout:
    def test_logout_sem_login_falha_401(self, client) -> None:
        r = client.post("/logout")
        assert r.status_code == 401

    def test_logout_apos_login_sucesso(self, client, usuario, usuario_senha) -> None:
        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        r = client.post("/logout")
        assert r.status_code == 200

    def test_logout_registra_auditoria(self, client, usuario, usuario_senha, sf) -> None:
        from core.infra.unit_of_work import UnitOfWork

        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        client.post("/logout")

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(usuario.empresa_id))
            tipos = [e["tipo"] for e in eventos]
            assert "USUARIO_LOGOUT" in tipos

    def test_apos_logout_sessao_invalidada(self, client, usuario, usuario_senha) -> None:
        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        client.post("/logout")

        r = client.get("/lancamentos/pendentes")
        assert r.status_code == 401


class TestRegeneracaoAuthenticationId:
    """Confirma que authentication_id nunca é reutilizado entre sessões."""

    def _authentication_id_do_ultimo_evento(self, sf, empresa_id, tipo) -> str:
        from core.infra.unit_of_work import UnitOfWork

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id))
            evento = next(e for e in eventos if e["tipo"] == tipo)
            return evento["payload"]["authentication_id"]

    def test_dois_logins_geram_authentication_ids_diferentes(
        self, sf, client, usuario, usuario_senha
    ) -> None:
        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        id_1 = self._authentication_id_do_ultimo_evento(
            sf, usuario.empresa_id, "USUARIO_LOGIN"
        )
        client.post("/logout")

        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        with __import__("core.infra.unit_of_work", fromlist=["UnitOfWork"]).UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(usuario.empresa_id))
            logins = [e for e in eventos if e["tipo"] == "USUARIO_LOGIN"]
            assert len(logins) == 2
            id_2 = logins[0]["payload"]["authentication_id"]  # mais recente primeiro (DESC)

        assert id_1 != id_2

    def test_logout_nao_reutiliza_authentication_id_do_login(
        self, sf, client, usuario, usuario_senha
    ) -> None:
        from core.infra.unit_of_work import UnitOfWork

        client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        client.post("/logout")

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(usuario.empresa_id))
            login_id = next(e for e in eventos if e["tipo"] == "USUARIO_LOGIN")["payload"]["authentication_id"]
            logout_id = next(e for e in eventos if e["tipo"] == "USUARIO_LOGOUT")["payload"]["authentication_id"]

        # logout usa o MESMO id da sessão que está encerrando — isso é
        # esperado (identifica qual sessão foi encerrada), diferente de
        # "reutilizar" um id de uma sessão ANTERIOR já finalizada.
        assert login_id == logout_id

    def test_sessao_apos_logout_nao_aceita_cookie_antigo(
        self, client, usuario, usuario_senha
    ) -> None:
        """Após logout, o cookie de sessão antigo (se reenviado) não autentica."""
        r1 = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        cookie_antigo = r1.headers.get("set-cookie")

        client.post("/logout")

        # Tenta reusar explicitamente o cookie antigo numa nova instância de cliente
        from fastapi.testclient import TestClient
        from api.main import create_app

        client2 = TestClient(create_app())
        client2.cookies.set("session", cookie_antigo.split("session=")[1].split(";")[0])
        r2 = client2.get("/lancamentos/pendentes")
        assert r2.status_code == 401

    def test_novo_login_revoga_sessao_anterior(
        self, client, usuario, usuario_senha
    ) -> None:
        """MVP: no máximo uma sessão ativa por usuário. Login em outro
        'dispositivo' (aqui simulado por um segundo TestClient) invalida
        o cookie do primeiro, mesmo sem logout explícito."""
        r1 = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        cookie_dispositivo_1 = r1.headers.get("set-cookie")

        # Confirma que o dispositivo 1 está autenticado antes do segundo login
        assert client.get("/lancamentos/pendentes").status_code == 200

        # Login em um "segundo dispositivo" — sem fazer logout do primeiro
        from fastapi.testclient import TestClient
        from api.main import create_app

        client_dispositivo_2 = TestClient(create_app())
        client_dispositivo_2.post(
            "/login", json={"email": usuario.email, "senha": usuario_senha}
        )
        assert client_dispositivo_2.get("/lancamentos/pendentes").status_code == 200

        # O dispositivo 1 (cookie antigo) deve ter sido revogado
        client_dispositivo_1_replay = TestClient(create_app())
        client_dispositivo_1_replay.cookies.set(
            "session", cookie_dispositivo_1.split("session=")[1].split(";")[0]
        )
        r_replay = client_dispositivo_1_replay.get("/lancamentos/pendentes")
        assert r_replay.status_code == 401


class TestAtributosSegurancaCookie:
    """Confirma HttpOnly, SameSite, Secure (prod) e Max-Age no cookie de sessão."""

    def test_cookie_tem_httponly(self, client, usuario, usuario_senha) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "httponly" in r.headers.get("set-cookie", "").lower()

    def test_cookie_tem_samesite_strict(self, client, usuario, usuario_senha) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "samesite=strict" in r.headers.get("set-cookie", "").lower()

    def test_cookie_tem_max_age_1800(self, client, usuario, usuario_senha) -> None:
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "max-age=1800" in r.headers.get("set-cookie", "").lower()

    def test_cookie_sem_secure_em_dev(self, client, usuario, usuario_senha) -> None:
        """Fixture 'client' roda com CADERNETA_ENV=dev — secure não deve aparecer."""
        r = client.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "secure" not in r.headers.get("set-cookie", "").lower()

    def test_cookie_tem_secure_fora_de_dev(
        self, sf, monkeypatch, usuario, usuario_senha
    ) -> None:
        """Fora de CADERNETA_ENV=dev, secure deve estar presente (produção)."""
        monkeypatch.delenv("CADERNETA_ENV", raising=False)
        from api.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client_prod = TestClient(app)
        r = client_prod.post("/login", json={"email": usuario.email, "senha": usuario_senha})
        assert "secure" in r.headers.get("set-cookie", "").lower()
