"""Login e logout — ADR 008 §4, §6, §7.

/login e /logout são as únicas rotas de mutação isentas do requisito
"autenticado previamente" (ADR 008 §8, lista fechada de exceções) —
por definição, ninguém está autenticado antes de logar.

Toda tentativa bem-sucedida de login/logout gera evento de auditoria
(USUARIO_LOGIN/USUARIO_LOGOUT) com papel + authentication_id, dentro da
mesma UnitOfWork da operação (ADR 008 §7).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

from api.auth.security import verificar_senha
from api.auth.session import encerrar_sessao, iniciar_sessao
from api.dependencies import get_current_user, get_session_factory
from core.audit.chain import TipoEvento
from core.domain.entities import Usuario
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

router = APIRouter(tags=["autenticação"])


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str


class UsuarioResponse(BaseModel):
    id: str
    email: str
    nome: str
    papel: str


@router.post("/login", response_model=UsuarioResponse)
def login(
    dados: LoginRequest,
    request: Request,
    session_factory: SessionFactory = Depends(get_session_factory),
) -> UsuarioResponse:
    """Autentica por e-mail/senha. Em caso de sucesso, grava a sessão e
    registra USUARIO_LOGIN no audit log."""
    with UnitOfWork(session_factory) as uow:
        usuario = uow.usuarios.buscar_por_email(dados.email)
        hash_armazenado = uow.usuarios.obter_hash_senha(dados.email)

        credenciais_validas = (
            usuario is not None
            and usuario.ativo
            and hash_armazenado is not None
            and verificar_senha(dados.senha, hash_armazenado)
        )

        if not credenciais_validas:
            # Mesma mensagem para e-mail inexistente e senha errada —
            # não revela qual dos dois estava incorreto.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha inválidos.",
            )

        session_id = iniciar_sessao(request, usuario)
        uow.usuarios.definir_sessao_ativa(usuario.id, session_id)

        uow.audit.registrar(
            tipo=TipoEvento.USUARIO_LOGIN,
            payload={
                "email": usuario.email,
                "papel": usuario.papel,
                "authentication_id": session_id,
            },
            usuario=str(usuario.id),
            empresa_id=str(usuario.empresa_id),
        )
        uow.commit()

    return UsuarioResponse(
        id=str(usuario.id),
        email=usuario.email,
        nome=usuario.nome,
        papel=usuario.papel,
    )


@router.post("/logout")
def logout(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> dict:
    """Encerra a sessão ativa e registra USUARIO_LOGOUT no audit log."""
    session_id = encerrar_sessao(request)

    with UnitOfWork(session_factory) as uow:
        uow.usuarios.invalidar_sessao_ativa(usuario.id)

        uow.audit.registrar(
            tipo=TipoEvento.USUARIO_LOGOUT,
            payload={
                "email": usuario.email,
                "papel": usuario.papel,
                "authentication_id": session_id,
            },
            usuario=str(usuario.id),
            empresa_id=str(usuario.empresa_id),
        )
        uow.commit()

    return {"status": "ok"}
