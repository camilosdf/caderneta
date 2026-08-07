"""FastAPI app factory — Interface Web do Caderneta (ADR 008, W1+W2).

W1: rotas de infraestrutura (/health, /ready, /live).
W2: autenticação (login/logout via sessão assinada) + primeiro endpoint
protegido (GET /lancamentos/pendentes).

Uso: uvicorn api.main:app
"""

import os
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.auth.session import montar_session_middleware, obter_secret_key
from api.routers import auth as auth_router
from api.routers import lancamentos as lancamentos_router
from core.infra.db.session import SessionFactory, session_factory_from_env


def _session_factory() -> Optional[SessionFactory]:
    """Resolve a SessionFactory a partir de DATABASE_URL.

    Mesma lógica de core/cli.py — DATABASE_URL define Postgres em produção;
    sem a variável, retorna None (ex.: em testes que injetam a factory
    diretamente, sem depender de ambiente).
    """
    return session_factory_from_env()


def create_app() -> FastAPI:
    """App factory — permite instanciar múltiplos apps isolados em testes."""
    app = FastAPI(
        title="Caderneta — Interface Web",
        description="Fila de aprovação e conciliação (ADR 008). "
        "CLI (core.cli) continua sendo o fluxo primário — esta API é aditiva.",
        # Documentação OpenAPI só habilitada explicitamente em dev (ADR 008 §8)
        docs_url="/docs" if os.getenv("CADERNETA_ENV") == "dev" else None,
        redoc_url="/redoc" if os.getenv("CADERNETA_ENV") == "dev" else None,
        openapi_url="/openapi.json" if os.getenv("CADERNETA_ENV") == "dev" else None,
    )

    montar_session_middleware(app, obter_secret_key())

    # ── Rotas de infraestrutura — únicas isentas de autenticação ────────
    # (ADR 008 §8: /login, /logout, /health, /ready, /live, OpenAPI em dev)

    @app.get("/health")
    def health() -> dict:
        """Liveness simples — o processo está de pé, sem checar dependências."""
        return {"status": "ok"}

    @app.get("/live")
    def live() -> dict:
        """Alias de /health — convenção comum (Kubernetes liveness probe)."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        """Readiness — verifica se o banco está acessível.

        Retorna 200 se DATABASE_URL não estiver definida (ex.: ambiente
        local usando SQLite via CLI, sem servidor web de fato em produção
        atrás dessa checagem) ou se a conexão for bem-sucedida; 503 se
        DATABASE_URL estiver definida mas a conexão falhar.
        """
        factory = _session_factory()
        if factory is None:
            return JSONResponse({"status": "ok", "banco": "não configurado"}, status_code=200)

        if factory.verificar_conexao():
            return JSONResponse({"status": "ok", "banco": "conectado"}, status_code=200)

        return JSONResponse({"status": "erro", "banco": "inacessível"}, status_code=503)

    # ── Rotas autenticadas (W2) ──────────────────────────────────────────
    app.include_router(auth_router.router)
    app.include_router(lancamentos_router.router)

    return app


app = create_app()
