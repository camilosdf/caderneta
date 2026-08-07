"""UsuarioRepository — persistência de Usuario (ADR 008).

Responsabilidade: converter entre Usuario (domínio) e UsuarioORM (banco).

Este repositório NUNCA interpreta ou verifica senha_hash — apenas
armazena e retorna o valor como um dado opaco. A verificação
(Argon2id) é responsabilidade exclusiva de api/auth/security.py,
nunca de core/ (ver ADR 008, matriz de importação: core nunca
importa api/).
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import Usuario
from core.infra.db.models import UsuarioORM


class EmailJaCadastradoError(Exception):
    """Já existe um usuário com este e-mail."""
    pass


class UsuarioRepository:
    """Repositório de Usuario — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def criar(self, usuario: Usuario, senha_hash: str) -> None:
        """Cria um novo usuário. Lança erro se o e-mail já existir."""
        if self.buscar_por_email(usuario.email) is not None:
            raise EmailJaCadastradoError(
                f"Já existe um usuário com o e-mail '{usuario.email}'."
            )
        orm = UsuarioORM(id=str(usuario.id))
        self._session.add(orm)
        _para_orm(usuario, senha_hash, orm)

    def salvar(self, usuario: Usuario, senha_hash: Optional[str] = None) -> None:
        """Atualiza um usuário existente. senha_hash é opcional —
        se omitido, o hash armazenado não é alterado."""
        orm = self._session.get(UsuarioORM, str(usuario.id))
        if orm is None:
            raise ValueError(f"Usuário {usuario.id} não encontrado para atualização.")
        _para_orm(usuario, senha_hash or orm.senha_hash, orm)

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, usuario_id: UUID) -> Optional[Usuario]:
        orm = self._session.get(UsuarioORM, str(usuario_id))
        return _para_dominio(orm) if orm else None

    def buscar_por_email(self, email: str) -> Optional[Usuario]:
        stmt = select(UsuarioORM).where(UsuarioORM.email == email)
        orm = self._session.execute(stmt).scalar_one_or_none()
        return _para_dominio(orm) if orm else None

    def obter_hash_senha(self, email: str) -> Optional[str]:
        """Retorna o hash bruto armazenado para o e-mail, ou None se não
        encontrado. Uso exclusivo da camada de autenticação (api/auth/).
        core/ nunca deve chamar isso para interpretar ou comparar o valor —
        apenas para repassá-lo à função de verificação em api/."""
        stmt = select(UsuarioORM.senha_hash).where(UsuarioORM.email == email)
        return self._session.execute(stmt).scalar_one_or_none()

    def listar_por_empresa(
        self,
        empresa_id: UUID,
        apenas_ativos: bool = False,
    ) -> list[Usuario]:
        stmt = select(UsuarioORM).where(UsuarioORM.empresa_id == str(empresa_id))
        if apenas_ativos:
            stmt = stmt.where(UsuarioORM.ativo == True)  # noqa: E712
        stmt = stmt.order_by(UsuarioORM.nome)
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    # ── Sessão ativa (achado de segurança do W2) ────────────────────────
    # O cookie assinado é só um portador de identidade — a revogação real
    # depende deste estado no servidor. Ver docstring de UsuarioORM.

    def definir_sessao_ativa(self, usuario_id: UUID, authentication_id: str) -> None:
        """Grava o authentication_id da sessão recém-criada no login.

        Sobrescreve qualquer sessão anterior — MVP permite no máximo uma
        sessão ativa por usuário (login em outro lugar revoga a anterior).
        """
        orm = self._session.get(UsuarioORM, str(usuario_id))
        if orm is None:
            raise ValueError(f"Usuário {usuario_id} não encontrado.")
        orm.current_authentication_id = authentication_id

    def sessao_ativa_confere(self, usuario_id: UUID, authentication_id: str) -> bool:
        """True somente se o authentication_id do cookie bate com o
        registrado no servidor para este usuário. Usado em toda requisição
        autenticada — nunca confia apenas na assinatura do cookie."""
        stmt = select(UsuarioORM.current_authentication_id).where(
            UsuarioORM.id == str(usuario_id)
        )
        atual = self._session.execute(stmt).scalar_one_or_none()
        return atual is not None and atual == authentication_id

    def invalidar_sessao_ativa(self, usuario_id: UUID) -> None:
        """Zera a sessão ativa — chamado no logout. Qualquer cópia do
        cookie antigo, mesmo com assinatura válida, deixa de autenticar
        imediatamente após esta chamada."""
        orm = self._session.get(UsuarioORM, str(usuario_id))
        if orm is not None:
            orm.current_authentication_id = None


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(usuario: Usuario, senha_hash: str, orm: UsuarioORM) -> None:
    orm.empresa_id = str(usuario.empresa_id)
    orm.email = usuario.email
    orm.nome = usuario.nome
    orm.papel = usuario.papel
    orm.senha_hash = senha_hash
    orm.ativo = usuario.ativo
    orm.criado_em = usuario.criado_em


def _para_dominio(orm: UsuarioORM) -> Usuario:
    return Usuario(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        email=orm.email,
        nome=orm.nome,
        papel=orm.papel,
        ativo=orm.ativo,
        criado_em=orm.criado_em,
    )
