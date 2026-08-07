"""Gerenciamento de sessão autenticada (ADR 008 §6).

Decisão de implementação do W2: cookie de sessão assinado via
Starlette SessionMiddleware, não JWT. Motivo: permite invalidação
imediata no logout sem precisar de blacklist — o débito técnico que o
ADR registrou como aceitável apenas se JWT stateless fosse escolhido.

authentication_id (ADR 008 §7, nomenclatura genérica para o audit log):
aqui é o session_id gerado a cada login, guardado dentro da própria
sessão assinada.
"""

import os
import secrets
from uuid import uuid4

from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware

from core.domain.entities import Usuario

EXPIRACAO_INATIVIDADE_SEGUNDOS = 30 * 60  # 30 minutos, ADR 008 §6


def obter_secret_key() -> str:
    """Resolve a chave de assinatura do cookie de sessão.

    Produção (CADERNETA_ENV != dev): exige CADERNETA_SECRET_KEY definida —
    falha ao iniciar em vez de rodar insegura silenciosamente.
    Dev: gera uma chave efêmera se não definida, com aviso explícito.
    """
    chave = os.getenv("CADERNETA_SECRET_KEY")
    if chave:
        return chave

    if os.getenv("CADERNETA_ENV") == "dev":
        print(
            "⚠ CADERNETA_SECRET_KEY não definida — usando chave efêmera de "
            "desenvolvimento. Sessões existentes invalidam a cada reinício. "
            "NUNCA use isso em produção."
        )
        return secrets.token_urlsafe(32)

    raise RuntimeError(
        "CADERNETA_SECRET_KEY não configurada. Obrigatória fora de "
        "desenvolvimento (CADERNETA_ENV=dev) — a Interface Web não inicia "
        "sem uma chave de assinatura de sessão explícita."
    )


def montar_session_middleware(app, secret_key: str) -> None:
    """Registra o SessionMiddleware na app FastAPI.

    https_only segue CADERNETA_ENV — só permite cookie sem HTTPS em dev,
    nunca em produção (ADR 008 §6: HttpOnly; Secure; SameSite=Strict).
    """
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        max_age=EXPIRACAO_INATIVIDADE_SEGUNDOS,
        same_site="strict",
        https_only=os.getenv("CADERNETA_ENV") != "dev",
    )


def iniciar_sessao(request: Request, usuario: Usuario) -> str:
    """Grava a identidade autenticada na sessão. Retorna o authentication_id
    (session_id) gerado, para uso no evento de auditoria USUARIO_LOGIN."""
    session_id = str(uuid4())
    request.session["usuario_id"] = str(usuario.id)
    request.session["papel"] = usuario.papel
    request.session["session_id"] = session_id
    return session_id


def encerrar_sessao(request: Request) -> str | None:
    """Limpa a sessão. Retorna o authentication_id que estava ativo (para
    o evento USUARIO_LOGOUT), ou None se não havia sessão."""
    session_id = request.session.get("session_id")
    request.session.clear()
    return session_id
