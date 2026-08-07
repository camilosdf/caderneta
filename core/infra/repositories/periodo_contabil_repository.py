"""PeriodoContabilRepository — persistência de PeriodoContabil.

Responsabilidade: converter entre PeriodoContabil (domínio) e
PeriodoContabilORM (banco), e executar queries por competência.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import PeriodoContabil, StatusPeriodo
from core.infra.db.models import PeriodoContabilORM


class PeriodoContabilRepository:
    """Repositório de PeriodoContabil — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar(self, periodo: PeriodoContabil) -> None:
        """Persiste ou atualiza um PeriodoContabil."""
        orm = self._session.get(PeriodoContabilORM, str(periodo.id))
        if orm is None:
            orm = PeriodoContabilORM(id=str(periodo.id))
            self._session.add(orm)
        _para_orm(periodo, orm)

    def obter_ou_criar(
        self,
        empresa_id: UUID,
        ano: int,
        mes: int,
    ) -> PeriodoContabil:
        """Retorna o período da competência, criando-o (aberto) se não existir."""
        periodo = self.buscar_por_competencia(empresa_id, ano, mes)
        if periodo is not None:
            return periodo
        periodo = PeriodoContabil(empresa_id=empresa_id, ano=ano, mes=mes)
        self.salvar(periodo)
        return periodo

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, periodo_id: UUID) -> Optional[PeriodoContabil]:
        orm = self._session.get(PeriodoContabilORM, str(periodo_id))
        return _para_dominio(orm) if orm else None

    def buscar_por_competencia(
        self,
        empresa_id: UUID,
        ano: int,
        mes: int,
    ) -> Optional[PeriodoContabil]:
        stmt = select(PeriodoContabilORM).where(
            PeriodoContabilORM.empresa_id == str(empresa_id),
            PeriodoContabilORM.ano == ano,
            PeriodoContabilORM.mes == mes,
        )
        orm = self._session.execute(stmt).scalar_one_or_none()
        return _para_dominio(orm) if orm else None

    def listar_por_empresa(
        self,
        empresa_id: UUID,
        status: Optional[StatusPeriodo] = None,
    ) -> list[PeriodoContabil]:
        stmt = select(PeriodoContabilORM).where(
            PeriodoContabilORM.empresa_id == str(empresa_id)
        )
        if status is not None:
            stmt = stmt.where(PeriodoContabilORM.status == status.value)
        stmt = stmt.order_by(PeriodoContabilORM.ano.desc(), PeriodoContabilORM.mes.desc())
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def mapa_por_competencia(
        self,
        empresa_id: UUID,
    ) -> dict[tuple[int, int], PeriodoContabil]:
        """Retorna todos os períodos da empresa indexados por (ano, mes).

        Uso típico: alimentar LancamentoService(periodos_por_competencia=...)
        antes de processar um lote de documentos que pode abranger vários meses.
        """
        periodos = self.listar_por_empresa(empresa_id)
        return {(p.ano, p.mes): p for p in periodos}


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(periodo: PeriodoContabil, orm: PeriodoContabilORM) -> None:
    orm.empresa_id = str(periodo.empresa_id)
    orm.ano = periodo.ano
    orm.mes = periodo.mes
    orm.status = periodo.status.value
    orm.fechado_por = periodo.fechado_por
    orm.fechado_em = periodo.fechado_em


def _para_dominio(orm: PeriodoContabilORM) -> PeriodoContabil:
    return PeriodoContabil(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        ano=orm.ano,
        mes=orm.mes,
        status=StatusPeriodo(orm.status),
        fechado_por=orm.fechado_por,
        fechado_em=orm.fechado_em,
    )
