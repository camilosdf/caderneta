"""AuditRepository — persistência de eventos de auditoria.

Substitui o AuditChain baseado em JSONL por persistência em banco.
Mantém a mesma semântica: append-only, hash chain imutável.

Interface compatível com AuditChain para facilitar substituição no pipeline (A5).
"""

from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.audit.chain import EventoAuditoria, TipoEvento
from core.infra.db.models import AuditEventoORM

_GENESIS = "GENESIS"


class AuditRepository:
    """Repositório de auditoria — append-only com hash chain."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._ultimo_hash: Optional[str] = None  # lazy — carregado na primeira escrita

    # ── Escrita ──────────────────────────────────────────────────────────

    def registrar(
        self,
        tipo: TipoEvento,
        payload: dict[str, Any],
        usuario: Optional[str] = None,
        empresa_id: Optional[str] = None,
        lancamento_id: Optional[str] = None,
        documento_id: Optional[str] = None,
        documento_hash: Optional[str] = None,
        campo_alterado: Optional[str] = None,
        valor_anterior: Optional[str] = None,
        valor_novo: Optional[str] = None,
        versao_regra: Optional[int] = None,
    ) -> EventoAuditoria:
        """Registra um evento na chain e persiste no banco."""
        from core.versao import VERSAO
        from datetime import datetime, timezone

        hash_anterior = self._carregar_ultimo_hash()

        evento = EventoAuditoria(
            id=str(uuid4()),
            tipo=tipo,
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            versao_sistema=VERSAO.pep440,
            payload=payload,
            hash_anterior=hash_anterior,
            usuario=usuario,
            empresa_id=empresa_id,
            lancamento_id=lancamento_id,
            documento_id=documento_id,
            documento_hash=documento_hash,
            campo_alterado=campo_alterado,
            valor_anterior=valor_anterior,
            valor_novo=valor_novo,
            versao_regra=versao_regra,
        )
        evento.hash_proprio = evento.calcular_hash()

        orm = AuditEventoORM(
            id=evento.id,
            hash_proprio=evento.hash_proprio,
            hash_anterior=evento.hash_anterior,
            tipo=evento.tipo.value,
            timestamp=evento.timestamp,
            versao_sistema=evento.versao_sistema,
            payload=evento.payload,
            usuario=evento.usuario,
            empresa_id=evento.empresa_id,
            lancamento_id=evento.lancamento_id,
            documento_id=evento.documento_id,
            documento_hash=evento.documento_hash,
            campo_alterado=evento.campo_alterado,
            valor_anterior=evento.valor_anterior,
            valor_novo=evento.valor_novo,
            versao_regra=evento.versao_regra,
        )
        self._session.add(orm)
        self._ultimo_hash = evento.hash_proprio
        return evento

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_documento(self, documento_hash: str) -> Optional[dict]:
        """Compatível com AuditChain.buscar_por_hash_documento()."""
        stmt = (
            select(AuditEventoORM)
            .where(AuditEventoORM.documento_hash == documento_hash)
            .order_by(AuditEventoORM.timestamp)
            .limit(1)
        )
        orm = self._session.execute(stmt).scalar_one_or_none()
        if orm is None:
            return None
        return {"timestamp": orm.timestamp, "id": orm.id}

    def listar_por_empresa(
        self,
        empresa_id: str,
        tipo: Optional[TipoEvento] = None,
        limit: int = 100,
    ) -> list[dict]:
        stmt = select(AuditEventoORM).where(
            AuditEventoORM.empresa_id == empresa_id
        )
        if tipo is not None:
            stmt = stmt.where(AuditEventoORM.tipo == tipo.value)
        stmt = stmt.order_by(AuditEventoORM.timestamp.desc()).limit(limit)
        return [_orm_para_dict(orm) for orm in self._session.execute(stmt).scalars()]

    def verificar_integridade(self, empresa_id: Optional[str] = None) -> tuple[bool, list[str]]:
        """Percorre a chain e verifica que cada hash_proprio é correto."""
        stmt = select(AuditEventoORM).order_by(AuditEventoORM.timestamp)
        if empresa_id:
            stmt = stmt.where(AuditEventoORM.empresa_id == empresa_id)

        erros: list[str] = []
        anterior = _GENESIS

        for orm in self._session.execute(stmt).scalars():
            if orm.hash_anterior != anterior:
                erros.append(
                    f"Evento {orm.id}: hash_anterior esperado={anterior!r}, "
                    f"encontrado={orm.hash_anterior!r}"
                )
            evento = _orm_para_evento(orm)
            calculado = evento.calcular_hash()
            if calculado != orm.hash_proprio:
                erros.append(
                    f"Evento {orm.id}: hash_proprio inválido — evento adulterado"
                )
            anterior = orm.hash_proprio

        return len(erros) == 0, erros

    def contar_por_tipo(self, empresa_id: Optional[str] = None) -> dict[str, int]:
        """Conta eventos agrupados por tipo — usado pelo comando `status` da CLI."""
        from sqlalchemy import func

        stmt = select(AuditEventoORM.tipo, func.count(AuditEventoORM.id))
        if empresa_id:
            stmt = stmt.where(AuditEventoORM.empresa_id == empresa_id)
        stmt = stmt.group_by(AuditEventoORM.tipo)

        return {tipo: qtd for tipo, qtd in self._session.execute(stmt).all()}

    # ── Internals ────────────────────────────────────────────────────────

    def _carregar_ultimo_hash(self) -> str:
        if self._ultimo_hash is not None:
            return self._ultimo_hash
        stmt = (
            select(AuditEventoORM.hash_proprio)
            .order_by(AuditEventoORM.timestamp.desc())
            .limit(1)
        )
        resultado = self._session.execute(stmt).scalar_one_or_none()
        self._ultimo_hash = resultado or _GENESIS
        return self._ultimo_hash


# =============================================================
# HELPERS
# =============================================================

def _orm_para_dict(orm: AuditEventoORM) -> dict:
    return {
        "id": orm.id,
        "tipo": orm.tipo,
        "timestamp": orm.timestamp,
        "versao_sistema": orm.versao_sistema,
        "hash_proprio": orm.hash_proprio,
        "hash_anterior": orm.hash_anterior,
        "usuario": orm.usuario,
        "empresa_id": orm.empresa_id,
        "lancamento_id": orm.lancamento_id,
        "documento_id": orm.documento_id,
        "documento_hash": orm.documento_hash,
        "campo_alterado": orm.campo_alterado,
        "valor_anterior": orm.valor_anterior,
        "valor_novo": orm.valor_novo,
        "versao_regra": orm.versao_regra,
        "payload": orm.payload,
    }


def _orm_para_evento(orm: AuditEventoORM) -> EventoAuditoria:
    return EventoAuditoria(
        id=orm.id,
        tipo=TipoEvento(orm.tipo),
        timestamp=orm.timestamp,
        versao_sistema=orm.versao_sistema,
        payload=orm.payload,
        hash_anterior=orm.hash_anterior,
        hash_proprio=orm.hash_proprio,
        usuario=orm.usuario,
        empresa_id=orm.empresa_id,
        lancamento_id=orm.lancamento_id,
        documento_id=orm.documento_id,
        documento_hash=orm.documento_hash,
        campo_alterado=orm.campo_alterado,
        valor_anterior=orm.valor_anterior,
        valor_novo=orm.valor_novo,
        versao_regra=orm.versao_regra,
    )
