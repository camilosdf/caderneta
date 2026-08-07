"""CentroCustoRepository — persistência de CentroCusto.

Responsabilidade: converter entre CentroCusto (domínio) e CentroCustoORM
(banco), e executar queries por código/empresa.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import CentroCusto
from core.infra.db.models import CentroCustoORM


class CentroCustoJaExisteError(Exception):
    """Já existe um centro de custo com este código para a empresa."""
    pass


class CentroCustoRepository:
    """Repositório de CentroCusto — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar(self, centro: CentroCusto) -> None:
        """Persiste ou atualiza um CentroCusto."""
        orm = self._session.get(CentroCustoORM, str(centro.id))
        if orm is None:
            orm = CentroCustoORM(id=str(centro.id))
            self._session.add(orm)
        _para_orm(centro, orm)

    def criar(self, empresa_id: UUID, codigo: str, nome: str) -> CentroCusto:
        """Cria um novo centro de custo. Lança erro se o código já existir."""
        if self.buscar_por_codigo(empresa_id, codigo) is not None:
            raise CentroCustoJaExisteError(
                f"Centro de custo '{codigo}' já existe para esta empresa."
            )
        centro = CentroCusto(empresa_id=empresa_id, codigo=codigo, nome=nome)
        self.salvar(centro)
        return centro

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, centro_id: UUID) -> Optional[CentroCusto]:
        orm = self._session.get(CentroCustoORM, str(centro_id))
        return _para_dominio(orm) if orm else None

    def buscar_por_codigo(self, empresa_id: UUID, codigo: str) -> Optional[CentroCusto]:
        stmt = select(CentroCustoORM).where(
            CentroCustoORM.empresa_id == str(empresa_id),
            CentroCustoORM.codigo == codigo,
        )
        orm = self._session.execute(stmt).scalar_one_or_none()
        return _para_dominio(orm) if orm else None

    def listar_por_empresa(
        self,
        empresa_id: UUID,
        apenas_ativos: bool = False,
    ) -> list[CentroCusto]:
        stmt = select(CentroCustoORM).where(
            CentroCustoORM.empresa_id == str(empresa_id)
        )
        if apenas_ativos:
            stmt = stmt.where(CentroCustoORM.ativo == True)  # noqa: E712
        stmt = stmt.order_by(CentroCustoORM.codigo)
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def mapa_por_codigo(self, empresa_id: UUID) -> dict[str, CentroCusto]:
        """Retorna todos os centros de custo da empresa indexados por código.

        Uso típico: alimentar LancamentoService(centros_por_codigo=...)
        antes de processar um lote de documentos.
        """
        centros = self.listar_por_empresa(empresa_id)
        return {c.codigo: c for c in centros}


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(centro: CentroCusto, orm: CentroCustoORM) -> None:
    orm.empresa_id = str(centro.empresa_id)
    orm.codigo = centro.codigo
    orm.nome = centro.nome
    orm.ativo = centro.ativo


def _para_dominio(orm: CentroCustoORM) -> CentroCusto:
    return CentroCusto(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        codigo=orm.codigo,
        nome=orm.nome,
        ativo=orm.ativo,
    )
