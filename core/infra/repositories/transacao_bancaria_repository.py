"""TransacaoBancariaRepository — Etapa 8.4.

Persistência de TransacaoBancaria com garantia de idempotência:
a combinação (instituição, conta, FITID) é única no banco —
reimportar o mesmo OFX é seguro (upsert ou skip por chave).
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import (
    ContaBancaria,
    Dinheiro,
    NaturezaLancamento,
    OrigemExtrato,
    TransacaoBancaria,
)
from core.infra.db.models import TransacaoBancariaORM


class TransacaoBancariaRepository:
    """Repositório de TransacaoBancaria."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar_se_nova(self, tx: TransacaoBancaria) -> bool:
        """Persiste apenas se a chave (instituição, conta, FITID) for nova.

        Retorna True se foi inserida, False se já existia (idempotente).
        """
        existente = self._buscar_orm_por_fitid(
            tx.conta_bancaria.instituicao,
            tx.conta_bancaria.numero_conta,
            tx.fitid,
        )
        if existente is not None:
            return False

        orm = TransacaoBancariaORM(
            id=str(tx.id),
            empresa_id=str(tx.empresa_id),
            instituicao=tx.conta_bancaria.instituicao,
            agencia=tx.conta_bancaria.agencia,
            numero_conta=tx.conta_bancaria.numero_conta,
            tipo_conta=tx.conta_bancaria.tipo_conta,
            fitid=tx.fitid,
            data=tx.data,
            valor=str(tx.valor.valor),
            natureza=tx.natureza.value,
            descricao=tx.descricao,
            referencia=tx.referencia,
            origem=tx.origem.value,
            id_importacao=tx.id_importacao,
            criado_em=tx.criado_em,
        )
        self._session.add(orm)
        return True

    # ── Leitura ──────────────────────────────────────────────────────────

    def listar_por_empresa_e_periodo(
        self,
        empresa_id: UUID,
        data_inicio: date,
        data_fim: date,
    ) -> list[TransacaoBancaria]:
        stmt = (
            select(TransacaoBancariaORM)
            .where(
                TransacaoBancariaORM.empresa_id == str(empresa_id),
                TransacaoBancariaORM.data >= data_inicio,
                TransacaoBancariaORM.data <= data_fim,
            )
            .order_by(TransacaoBancariaORM.data)
        )
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def buscar_por_fitid(
        self,
        empresa_id: UUID,
        instituicao: str,
        numero_conta: str,
        fitid: str,
    ) -> TransacaoBancaria | None:
        orm = self._buscar_orm_por_fitid(instituicao, numero_conta, fitid)
        if orm is None or orm.empresa_id != str(empresa_id):
            return None
        return _para_dominio(orm)

    # ── Internos ──────────────────────────────────────────────────────────

    def _buscar_orm_por_fitid(
        self, instituicao: str, numero_conta: str, fitid: str
    ) -> TransacaoBancariaORM | None:
        stmt = select(TransacaoBancariaORM).where(
            TransacaoBancariaORM.instituicao == instituicao,
            TransacaoBancariaORM.numero_conta == numero_conta,
            TransacaoBancariaORM.fitid == fitid,
        )
        return self._session.execute(stmt).scalar_one_or_none()


# =============================================================
# MAPEAMENTO ORM → DOMÍNIO
# =============================================================

def _para_dominio(orm: TransacaoBancariaORM) -> TransacaoBancaria:
    from datetime import datetime, timezone
    return TransacaoBancaria(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        conta_bancaria=ContaBancaria(
            instituicao=orm.instituicao,
            agencia=orm.agencia,
            numero_conta=orm.numero_conta,
            tipo_conta=orm.tipo_conta,
        ),
        fitid=orm.fitid,
        data=orm.data,
        valor=Dinheiro(Decimal(orm.valor)),
        natureza=NaturezaLancamento(orm.natureza),
        descricao=orm.descricao,
        referencia=orm.referencia,
        origem=OrigemExtrato(orm.origem),
        id_importacao=orm.id_importacao,
        criado_em=orm.criado_em,
    )
