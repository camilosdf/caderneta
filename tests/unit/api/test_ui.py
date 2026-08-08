"""Testes da interface visual (ADR 008, W4).

Cobre: página de login renderiza HTML, fila exige autenticação, fragmento
HTMX retorna só as linhas (não HTML completo), fluxo login → fila → fragmento
end-to-end, estático servido corretamente.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth.security import hash_senha
from api.main import create_app
from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    Usuario,
)
from core.infra.db import SessionFactory
from core.infra.repositories import LancamentoRepository, UsuarioRepository


@pytest.fixture
def sf(monkeypatch, tmp_path) -> SessionFactory:
    db_path = tmp_path / "test_ui.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    factory = SessionFactory(f"sqlite:///{db_path}")
    factory.criar_tabelas()
    return factory


@pytest.fixture
def client(sf: SessionFactory) -> TestClient:
    return TestClient(create_app())


def _usuario(sf, empresa_id, email="ui@x.com", papel="contador") -> Usuario:
    u = Usuario(empresa_id=empresa_id, email=email, nome="Teste UI", papel=papel)
    with sf.session() as session:
        UsuarioRepository(session).criar(u, senha_hash=hash_senha("Senha123!"))
    return u


def _lancamento(sf, empresa_id, descricao="UI Teste") -> Lancamento:
    lanc = Lancamento(
        empresa_id=empresa_id,
        descricao=descricao,
        status=StatusLancamento.PENDENTE,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=date(2026, 6, 1),
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal("250.00"))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal("250.00"))),
        ],
    )
    with sf.session() as session:
        LancamentoRepository(session).salvar(lanc)
    return lanc


class TestPaginaLogin:
    def test_retorna_html(self, client) -> None:
        r = client.get("/login")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_contem_formulario_de_login(self, client) -> None:
        r = client.get("/login")
        assert 'hx-post="/login"' in r.text or 'action="/login"' in r.text
        assert "E-mail" in r.text
        assert "Senha" in r.text

    def test_contem_htmx(self, client) -> None:
        r = client.get("/login")
        assert "htmx" in r.text or "/static/htmx.min.js" in r.text


class TestRaizRedirect:
    def test_redireciona_para_fila(self, client) -> None:
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "/fila" in r.headers["location"]


class TestPaginaFila:
    def test_sem_auth_retorna_401(self, client) -> None:
        r = client.get("/fila")
        assert r.status_code == 401

    def test_com_auth_retorna_html(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/fila")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_fila_mostra_nome_usuario(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/fila")
        assert "Teste UI" in r.text

    def test_fila_contem_trigger_htmx(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/fila")
        assert "hx-get" in r.text


class TestFragmentoLinhas:
    def test_sem_auth_retorna_401(self, client) -> None:
        r = client.get("/ui/fila/linhas")
        assert r.status_code == 401

    def test_com_auth_retorna_html_parcial(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/ui/fila/linhas")
        assert r.status_code == 200
        # Fragmento não tem <html> completo
        assert "<html" not in r.text.lower()

    def test_lista_lancamentos_pendentes(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        _lancamento(sf, empresa_id, descricao="Fornecedor XYZ")
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/ui/fila/linhas")
        assert "Fornecedor XYZ" in r.text

    def test_nao_vaza_lancamentos_de_outra_empresa(self, sf, client) -> None:
        empresa_a = uuid4()
        empresa_b = uuid4()
        _usuario(sf, empresa_a, email="ui@x.com")
        _lancamento(sf, empresa_b, descricao="Secredo empresa B")
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/ui/fila/linhas")
        assert "Secredo empresa B" not in r.text

    def test_vazio_quando_sem_pendentes(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/ui/fila/linhas")
        assert r.status_code == 200
        assert "pendente" not in r.text.lower() or "Nenhum" in r.text

    def test_contem_botoes_de_decisao(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id)
        _lancamento(sf, empresa_id)
        client.post("/login", json={"email": "ui@x.com", "senha": "Senha123!"})

        r = client.get("/ui/fila/linhas")
        assert "Aprovar" in r.text
        assert "Rejeitar" in r.text
        assert "hx-post" in r.text


class TestEstaticoHTMX:
    def test_htmx_js_servido(self, client) -> None:
        r = client.get("/static/htmx.min.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "")
        # htmx tem um identificador reconhecível no fonte
        assert "htmx" in r.text[:500].lower()
