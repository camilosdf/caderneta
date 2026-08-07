"""Testes do esqueleto FastAPI — api/main.py (ADR 008, W1).

Cobre: /health, /live, /ready (com e sem banco configurado/acessível),
e que /docs fica desabilitado por padrão (só habilita com CADERNETA_ENV=dev).
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CADERNETA_ENV", raising=False)
    app = create_app()
    return TestClient(app)


class TestRotasInfraestrutura:
    def test_health_responde_200(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_live_responde_200(self, client: TestClient) -> None:
        r = client.get("/live")
        assert r.status_code == 200

    def test_ready_sem_database_url_responde_200(self, client: TestClient) -> None:
        """Sem DATABASE_URL configurada, /ready não falha — apenas informa."""
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["banco"] == "não configurado"

    def test_ready_com_banco_sqlite_valido_responde_200(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        app = create_app()
        client = TestClient(app)
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["banco"] == "conectado"


class TestDocumentacaoOpenAPI:
    def test_docs_desabilitado_por_padrao(self, client: TestClient) -> None:
        r = client.get("/docs")
        assert r.status_code == 404

    def test_redoc_desabilitado_por_padrao(self, client: TestClient) -> None:
        r = client.get("/redoc")
        assert r.status_code == 404

    def test_openapi_json_desabilitado_por_padrao(self, client: TestClient) -> None:
        r = client.get("/openapi.json")
        assert r.status_code == 404

    def test_docs_habilitado_em_dev(self, monkeypatch) -> None:
        monkeypatch.setenv("CADERNETA_ENV", "dev")
        app = create_app()
        client = TestClient(app)
        r = client.get("/docs")
        assert r.status_code == 200
