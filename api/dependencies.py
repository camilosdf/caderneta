"""Dependências FastAPI — sessão de banco, identidade autenticada, RBAC.

Implementa o padrão do ADR 008 §9:

    HTTP Request → Middleware/Dependency → request.session["usuario_id"]
                 → Endpoint → Caso de uso → PolicyEngine (decide)

get_current_user() é o único ponto que lê identidade — sempre da sessão
assinada pelo servidor, nunca de dados enviados pelo cliente na própria
requisição (corolário anti-falsificação, ADR 008 §9).
"""

import os
from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from core.domain.entities import Usuario
from core.infra.db.session import SessionFactory, session_factory_from_env
from core.infra.unit_of_work import UnitOfWork


def get_session_factory() -> SessionFactory:
    """Resolve a SessionFactory a partir de DATABASE_URL.

    Diferente de /ready (W1), que tolera ausência de banco, endpoints
    autenticados exigem banco configurado — sem ele, não há onde
    verificar credenciais nem persistir auditoria.
    """
    factory = session_factory_from_env()
    if factory is None:
        raise RuntimeError(
            "DATABASE_URL não configurada — necessária para autenticação "
            "e persistência. Endpoints protegidos não funcionam sem banco."
        )
    return factory


def get_current_user(
    request: Request,
    session_factory: SessionFactory = Depends(get_session_factory),
) -> Usuario:
    """Extrai o usuário autenticado, validando em duas camadas:

    1. Assinatura do cookie (feita pelo SessionMiddleware antes de chegar
       aqui — request.session já vem vazio se a assinatura for inválida).
    2. O authentication_id do cookie precisa bater com o registrado no
       servidor (UsuarioRepository.sessao_ativa_confere) — sem isso, um
       cookie capturado antes de um logout continuaria autenticando
       indefinidamente até expirar por tempo, mesmo após o usuário ter
       encerrado a sessão explicitamente (achado de segurança do W2).

    Nunca lê usuario_id de body, query string, ou header manipulável —
    apenas de request.session, que só o servidor escreve.
    """
    usuario_id_str = request.session.get("usuario_id")
    authentication_id = request.session.get("session_id")

    if not usuario_id_str or not authentication_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado.",
        )

    try:
        usuario_id = UUID(usuario_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida.",
        )

    with UnitOfWork(session_factory) as uow:
        usuario = uow.usuarios.buscar_por_id(usuario_id)
        sessao_valida = uow.usuarios.sessao_ativa_confere(usuario_id, authentication_id)

    if usuario is None or not usuario.ativo or not sessao_valida:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado.",
        )

    return usuario


def require_role(*papeis_permitidos: str) -> Callable[[Usuario], Usuario]:
    """Factory de dependency para restringir uma rota a papéis específicos.

    Uso: @router.post("/algo") def rota(usuario: Usuario = Depends(require_role("supervisor", "admin"))): ...

    Esta função apenas verifica IDENTIDADE/PAPEL para controle de acesso à
    rota — não decide regras de negócio (ex.: alçada de valor). Essas
    decisões continuam exclusivamente no domínio (PolicyEngine), conforme
    ADR 008 §9. require_role é sobre "quem pode bater nesta porta", não
    "o que a pessoa pode fazer depois de entrar".
    """

    def verificador(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.papel not in papeis_permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sem permissão para esta ação.",
            )
        return usuario

    return verificador


def ambiente_dev() -> bool:
    """True se CADERNETA_ENV=dev — controla docs OpenAPI, https_only, etc."""
    return os.getenv("CADERNETA_ENV") == "dev"
