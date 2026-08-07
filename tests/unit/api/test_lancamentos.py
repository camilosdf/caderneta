"""Testes de GET /lancamentos/pendentes (ADR 008, W2).

Cobre: exige autenticação, retorna só lançamentos PENDENTE da empresa do
usuário logado, não vaza lançamentos de outra empresa, formato de resposta.
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
    db_path = tmp_path / "test_lanc.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    factory = SessionFactory(f"sqlite:///{db_path}")
    factory.criar_tabelas()
    return factory


@pytest.fixture
def client(sf: SessionFactory) -> TestClient:
    return TestClient(create_app())


def _criar_usuario(sf: SessionFactory, empresa_id, email="user@x.com", senha="Senha123!") -> Usuario:
    u = Usuario(empresa_id=empresa_id, email=email, nome="Teste", papel="contador")
    with sf.session() as session:
        UsuarioRepository(session).criar(u, senha_hash=hash_senha(senha))
    return u


def _criar_lancamento(sf: SessionFactory, empresa_id, status: StatusLancamento, descricao="Teste") -> Lancamento:
    lanc = Lancamento(
        empresa_id=empresa_id,
        descricao=descricao,
        status=status,
        nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        data_lancamento=date(2026, 6, 1),
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal("100.00"))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal("100.00"))),
        ],
    )
    with sf.session() as session:
        LancamentoRepository(session).salvar(lanc)
    return lanc


class TestListarPendentesAutenticacao:
    def test_sem_login_retorna_401(self, client) -> None:
        r = client.get("/lancamentos/pendentes")
        assert r.status_code == 401

    def test_com_login_retorna_200(self, sf, client) -> None:
        empresa_id = uuid4()
        _criar_usuario(sf, empresa_id)
        client.post("/login", json={"email": "user@x.com", "senha": "Senha123!"})

        r = client.get("/lancamentos/pendentes")
        assert r.status_code == 200


class TestListarPendentesConteudo:
    def test_retorna_apenas_pendentes(self, sf, client) -> None:
        empresa_id = uuid4()
        _criar_usuario(sf, empresa_id)
        _criar_lancamento(sf, empresa_id, StatusLancamento.PENDENTE, "Pendente 1")
        _criar_lancamento(sf, empresa_id, StatusLancamento.APROVADO, "Aprovado 1")
        _criar_lancamento(sf, empresa_id, StatusLancamento.EXPORTADO, "Exportado 1")

        client.post("/login", json={"email": "user@x.com", "senha": "Senha123!"})
        r = client.get("/lancamentos/pendentes")

        dados = r.json()
        assert len(dados) == 1
        assert dados[0]["descricao"] == "Pendente 1"

    def test_nao_vaza_lancamento_de_outra_empresa(self, sf, client) -> None:
        empresa_a = uuid4()
        empresa_b = uuid4()
        _criar_usuario(sf, empresa_a, email="a@x.com")
        _criar_lancamento(sf, empresa_a, StatusLancamento.PENDENTE, "Da empresa A")
        _criar_lancamento(sf, empresa_b, StatusLancamento.PENDENTE, "Da empresa B")

        client.post("/login", json={"email": "a@x.com", "senha": "Senha123!"})
        r = client.get("/lancamentos/pendentes")

        dados = r.json()
        assert len(dados) == 1
        assert dados[0]["descricao"] == "Da empresa A"

    def test_formato_da_resposta(self, sf, client) -> None:
        empresa_id = uuid4()
        _criar_usuario(sf, empresa_id)
        _criar_lancamento(sf, empresa_id, StatusLancamento.PENDENTE, "Formato")

        client.post("/login", json={"email": "user@x.com", "senha": "Senha123!"})
        r = client.get("/lancamentos/pendentes")

        item = r.json()[0]
        assert set(item.keys()) == {
            "id", "data_lancamento", "descricao", "valor_total", "status", "categoria"
        }
        assert item["valor_total"] == "100.00" or float(item["valor_total"]) == 100.00
        assert item["status"] == "pendente"

    def test_lista_vazia_quando_sem_pendentes(self, sf, client) -> None:
        empresa_id = uuid4()
        _criar_usuario(sf, empresa_id)

        client.post("/login", json={"email": "user@x.com", "senha": "Senha123!"})
        r = client.get("/lancamentos/pendentes")

        assert r.json() == []
