"""ContaContabilRepository — persistência de ContaContabil (DT-CC-01, ADR 011).

B.2.1 — cadastro apenas. Sem FK ativa ainda (ver ContaContabilORM,
core/infra/db/models.py, e ADR 011 para a sequência B.2.1-B.2.4).

Responsabilidade: converter entre ContaContabil (domínio) e
ContaContabilORM (banco), e executar queries por código/empresa. Mesmo
formato de core/infra/repositories/centro_custo_repository.py.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import CodigoConta, ContaContabil, NaturezaLancamento
from core.infra.db.models import ContaContabilORM


class ContaContabilJaExisteError(Exception):
    """Já existe uma conta contábil com este código para a empresa."""
    pass


class ContaContabilRepository:
    """Repositório de ContaContabil — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar(self, conta: ContaContabil) -> None:
        """Persiste ou atualiza uma ContaContabil."""
        orm = self._session.get(ContaContabilORM, str(conta.id))
        if orm is None:
            orm = ContaContabilORM(id=str(conta.id))
            self._session.add(orm)
        _para_orm(conta, orm)

    def criar(
        self,
        empresa_id: UUID,
        codigo: str,
        nome: str,
        natureza: NaturezaLancamento = NaturezaLancamento.DEBITO,
        tipo: str = "",
        permite_lancamento: bool = True,
        centro_custo_obrigatorio: bool = False,
    ) -> ContaContabil:
        """Cria uma nova conta contábil. Lança erro se o código já existir."""
        if self.buscar_por_codigo(empresa_id, codigo) is not None:
            raise ContaContabilJaExisteError(
                f"Conta contábil '{codigo}' já existe para esta empresa."
            )
        conta = ContaContabil(
            empresa_id=empresa_id,
            codigo=CodigoConta(codigo),
            nome=nome,
            natureza=natureza,
            tipo=tipo,
            permite_lancamento=permite_lancamento,
            centro_custo_obrigatorio=centro_custo_obrigatorio,
        )
        self.salvar(conta)
        return conta

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, conta_id: UUID) -> Optional[ContaContabil]:
        orm = self._session.get(ContaContabilORM, str(conta_id))
        return _para_dominio(orm) if orm else None

    def buscar_por_codigo(self, empresa_id: UUID, codigo: str) -> Optional[ContaContabil]:
        stmt = select(ContaContabilORM).where(
            ContaContabilORM.empresa_id == str(empresa_id),
            ContaContabilORM.codigo == codigo,
        )
        orm = self._session.execute(stmt).scalar_one_or_none()
        return _para_dominio(orm) if orm else None

    def listar_por_empresa(self, empresa_id: UUID) -> list[ContaContabil]:
        stmt = (
            select(ContaContabilORM)
            .where(ContaContabilORM.empresa_id == str(empresa_id))
            .order_by(ContaContabilORM.codigo)
        )
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def mapa_por_codigo(self, empresa_id: UUID) -> dict[str, ContaContabil]:
        """Retorna todas as contas contábeis da empresa indexadas por código.

        Uso típico: alimentar LancamentoService(contas_por_codigo=...)
        antes de processar um lote de documentos — mesmo padrão já usado
        por CentroCustoRepository.mapa_por_codigo.
        """
        contas = self.listar_por_empresa(empresa_id)
        return {c.codigo.codigo: c for c in contas}


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(conta: ContaContabil, orm: ContaContabilORM) -> None:
    orm.empresa_id = str(conta.empresa_id)
    orm.codigo = conta.codigo.codigo
    orm.nome = conta.nome
    orm.tipo = conta.tipo
    orm.natureza = conta.natureza.value
    orm.guid_gnucash = conta.guid_gnucash
    orm.permite_lancamento = conta.permite_lancamento
    orm.centro_custo_obrigatorio = conta.centro_custo_obrigatorio
    orm.conta_pai_id = str(conta.conta_pai_id) if conta.conta_pai_id else None
    orm.versao = conta.versao


def _para_dominio(orm: ContaContabilORM) -> ContaContabil:
    return ContaContabil(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        codigo=CodigoConta(orm.codigo),
        nome=orm.nome,
        tipo=orm.tipo,
        natureza=NaturezaLancamento(orm.natureza),
        guid_gnucash=orm.guid_gnucash,
        permite_lancamento=orm.permite_lancamento,
        centro_custo_obrigatorio=orm.centro_custo_obrigatorio,
        conta_pai_id=UUID(orm.conta_pai_id) if orm.conta_pai_id else None,
        versao=orm.versao,
    )
