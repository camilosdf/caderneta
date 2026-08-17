"""LancamentoRepository — persistência de Lancamento e Split.

Responsabilidade: converter entre Lancamento/Split (domínio) e ORM,
e executar queries relacionadas a lançamentos contábeis.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
)
from core.infra.db.models import LancamentoORM, SplitORM


class LancamentoRepository:
    """Repositório de Lancamento — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar(self, lancamento: Lancamento) -> None:
        """Persiste ou atualiza um Lancamento com seus Splits."""
        orm = self._session.get(LancamentoORM, str(lancamento.id))
        if orm is None:
            orm = LancamentoORM(id=str(lancamento.id))
            self._session.add(orm)
        _para_orm(lancamento, orm)

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, lancamento_id: UUID) -> Optional[Lancamento]:
        orm = self._session.get(LancamentoORM, str(lancamento_id))
        return _para_dominio(orm) if orm else None

    def listar_por_documento(self, documento_id: UUID) -> list[Lancamento]:
        stmt = select(LancamentoORM).where(
            LancamentoORM.documento_id == str(documento_id)
        )
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def listar_por_empresa(
        self,
        empresa_id: UUID,
        status: Optional[StatusLancamento] = None,
        data_inicio: Optional[date] = None,
        data_fim: Optional[date] = None,
        precisa_revisao: Optional[bool] = None,
        limit: int = 100,
    ) -> list[Lancamento]:
        stmt = select(LancamentoORM).where(
            LancamentoORM.empresa_id == str(empresa_id)
        )
        if status is not None:
            stmt = stmt.where(LancamentoORM.status == status.value)
        if data_inicio is not None:
            stmt = stmt.where(LancamentoORM.data_lancamento >= data_inicio)
        if data_fim is not None:
            stmt = stmt.where(LancamentoORM.data_lancamento <= data_fim)
        if precisa_revisao is not None:
            if precisa_revisao:
                stmt = stmt.where(LancamentoORM.pre_aprovado == False)  # noqa: E712
            else:
                stmt = stmt.where(LancamentoORM.pre_aprovado == True)  # noqa: E712
        stmt = stmt.limit(limit).order_by(LancamentoORM.data_lancamento.desc())
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def deletar(self, lancamento_id: UUID) -> bool:
        orm = self._session.get(LancamentoORM, str(lancamento_id))
        if orm is None:
            return False
        self._session.delete(orm)
        return True


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(lanc: Lancamento, orm: LancamentoORM) -> None:
    orm.empresa_id = str(lanc.empresa_id)
    orm.documento_id = str(lanc.documento_id) if lanc.documento_id else None
    orm.fornecedor_id = str(lanc.fornecedor_id) if lanc.fornecedor_id else None
    orm.data_lancamento = lanc.data_lancamento
    orm.data_competencia = lanc.data_competencia
    orm.criado_em = lanc.criado_em
    orm.descricao = lanc.descricao
    orm.historico_padronizado = lanc.historico_padronizado
    orm.e_parcelado = lanc.e_parcelado
    orm.parcela_atual = lanc.parcela_atual
    orm.total_parcelas = lanc.total_parcelas
    orm.lancamento_pai_id = str(lanc.lancamento_pai_id) if lanc.lancamento_pai_id else None
    orm.categoria = lanc.categoria
    orm.confidence = lanc.confidence
    orm.metodo_classificacao = lanc.metodo_classificacao
    orm.regra_aplicada_id = str(lanc.regra_aplicada_id) if lanc.regra_aplicada_id else None
    orm.versao_regra = lanc.versao_regra
    orm.status = lanc.status.value
    orm.nivel_aprovacao = lanc.nivel_aprovacao.value if lanc.nivel_aprovacao else None
    orm.pre_aprovado = lanc.pre_aprovado
    orm.criado_por = lanc.criado_por
    orm.aprovado_por_1 = lanc.aprovado_por_1
    orm.aprovado_em_1 = lanc.aprovado_em_1
    orm.aprovado_por_2 = lanc.aprovado_por_2
    orm.aprovado_em_2 = lanc.aprovado_em_2
    orm.guid_gnucash = lanc.guid_gnucash
    orm.exportado_em = lanc.exportado_em

    # Substitui splits existentes pelos atuais
    orm.splits = [_split_para_orm(s, str(lanc.id)) for s in lanc.splits]


def _para_dominio(orm: LancamentoORM) -> Lancamento:
    lanc = Lancamento(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        documento_id=UUID(orm.documento_id) if orm.documento_id else None,
        fornecedor_id=UUID(orm.fornecedor_id) if orm.fornecedor_id else None,
        data_lancamento=orm.data_lancamento,
        data_competencia=orm.data_competencia,
        criado_em=orm.criado_em,
        descricao=orm.descricao,
        historico_padronizado=orm.historico_padronizado,
        e_parcelado=orm.e_parcelado,
        parcela_atual=orm.parcela_atual,
        total_parcelas=orm.total_parcelas,
        lancamento_pai_id=UUID(orm.lancamento_pai_id) if orm.lancamento_pai_id else None,
        categoria=orm.categoria,
        confidence=float(orm.confidence) if orm.confidence is not None else None,
        metodo_classificacao=orm.metodo_classificacao,
        regra_aplicada_id=UUID(orm.regra_aplicada_id) if orm.regra_aplicada_id else None,
        versao_regra=orm.versao_regra,
        status=StatusLancamento(orm.status),
        nivel_aprovacao=NivelAprovacao(orm.nivel_aprovacao) if orm.nivel_aprovacao else None,
        pre_aprovado=orm.pre_aprovado,
        criado_por=orm.criado_por,
        aprovado_por_1=orm.aprovado_por_1,
        aprovado_em_1=orm.aprovado_em_1,
        aprovado_por_2=orm.aprovado_por_2,
        aprovado_em_2=orm.aprovado_em_2,
        guid_gnucash=orm.guid_gnucash,
        exportado_em=orm.exportado_em,
        splits=[_split_para_dominio(s) for s in orm.splits],
    )
    return lanc


def _split_para_orm(split: Split, lancamento_id: str) -> SplitORM:
    return SplitORM(
        id=str(split.id),
        lancamento_id=lancamento_id,
        conta_codigo=split.conta.codigo,
        natureza=split.natureza.value,
        valor=split.valor.valor,
        moeda=split.valor.moeda,
        centro_custo=split.centro_custo,
        descricao=split.descricao,
    )


def _split_para_dominio(orm: SplitORM) -> Split:
    return Split(
        id=UUID(orm.id),
        conta=CodigoConta(orm.conta_codigo),
        natureza=NaturezaLancamento(orm.natureza),
        valor=Dinheiro(orm.valor, orm.moeda),
        centro_custo=orm.centro_custo,
        descricao=orm.descricao,
    )
