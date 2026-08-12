"""CartaoCreditoRepository / FaturaCartaoRepository — ADR 010, Fase 4.

Persistência com garantia de idempotência (D13):
  - CartaoCredito: chave natural (empresa_id, emissor, final_numero, titular)
    — mesmo cartão nunca gera duas linhas (Deliberação Complementar, B1).
  - FaturaCartao: chave natural (cartao_id, periodo_referencia) — mesma
    fatura reenviada não duplica (ADR 010, D13). Os itens (CompraCartao)
    são persistidos em cascata junto da fatura; como a fatura duplicada
    nunca chega a ser inserida, os itens duplicados também não chegam
    a ser tocados — a checagem de nível fatura já cobre o nível item
    nesta primeira versão (reprocessamento parcial de itens isolados
    fica fora do escopo desta fase).

Mesmo padrão de TransacaoBancariaRepository.salvar_se_nova: checa
existência por chave antes de inserir; retorna bool indicando se houve
inserção.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    Dinheiro,
    FaturaCartao,
    StatusFechamentoFatura,
    TipoItemFatura,
)
from core.infra.db.models import CartaoCreditoORM, CompraCartaoORM, FaturaCartaoORM


class CartaoCreditoRepository:
    """Repositório de CartaoCredito — idempotência por identidade (B1)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def salvar_se_novo(self, cartao: CartaoCredito) -> bool:
        """Persiste apenas se a chave de identidade for nova.

        Retorna True se foi inserido, False se já existia (idempotente).
        """
        existente = self._buscar_orm_por_chave(
            str(cartao.empresa_id), cartao.emissor, cartao.final_numero, cartao.titular
        )
        if existente is not None:
            return False

        orm = CartaoCreditoORM(
            id=str(cartao.id),
            empresa_id=str(cartao.empresa_id),
            emissor=cartao.emissor,
            final_numero=cartao.final_numero,
            titular=cartao.titular,
            conta_codigo=cartao.conta_codigo.codigo,
            guid_gnucash=cartao.guid_gnucash,
            ativo=cartao.ativo,
            criado_em=cartao.criado_em,
        )
        self._session.add(orm)
        return True

    def buscar_por_chave(
        self, empresa_id: UUID, emissor: str, final_numero: str, titular: str
    ) -> CartaoCredito | None:
        orm = self._buscar_orm_por_chave(str(empresa_id), emissor, final_numero, titular)
        return _cartao_para_dominio(orm) if orm else None

    def buscar_por_id(self, cartao_id: UUID) -> CartaoCredito | None:
        orm = self._session.get(CartaoCreditoORM, str(cartao_id))
        return _cartao_para_dominio(orm) if orm else None

    def _buscar_orm_por_chave(
        self, empresa_id: str, emissor: str, final_numero: str, titular: str
    ) -> CartaoCreditoORM | None:
        stmt = select(CartaoCreditoORM).where(
            CartaoCreditoORM.empresa_id == empresa_id,
            CartaoCreditoORM.emissor == emissor,
            CartaoCreditoORM.final_numero == final_numero,
            CartaoCreditoORM.titular == titular,
        )
        return self._session.execute(stmt).scalar_one_or_none()


class FaturaCartaoRepository:
    """Repositório de FaturaCartao — idempotência por (cartão, período)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def salvar_se_nova(self, fatura: FaturaCartao) -> bool:
        """Persiste a fatura e seus itens apenas se (cartao_id,
        periodo_referencia) for uma chave nova.

        Retorna True se foi inserida, False se já existia (idempotente).
        Fatura duplicada não é tocada — seus itens também não são
        inseridos nem comparados.
        """
        existente = self._buscar_orm_por_chave(
            str(fatura.cartao_id), fatura.periodo_referencia
        )
        if existente is not None:
            return False

        orm = FaturaCartaoORM(id=str(fatura.id))
        _fatura_para_orm(fatura, orm)
        self._session.add(orm)
        return True

    def buscar_por_cartao_e_periodo(
        self, cartao_id: UUID, periodo_referencia: date
    ) -> FaturaCartao | None:
        orm = self._buscar_orm_por_chave(str(cartao_id), periodo_referencia)
        return _fatura_para_dominio(orm) if orm else None

    def buscar_por_id(self, fatura_id: UUID) -> FaturaCartao | None:
        orm = self._session.get(FaturaCartaoORM, str(fatura_id))
        return _fatura_para_dominio(orm) if orm else None

    def listar_por_empresa(self, empresa_id: UUID) -> list[FaturaCartao]:
        stmt = (
            select(FaturaCartaoORM)
            .where(FaturaCartaoORM.empresa_id == str(empresa_id))
            .order_by(FaturaCartaoORM.periodo_referencia.desc())
        )
        return [_fatura_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def atualizar_lancamento_ids_dos_itens(self, fatura: FaturaCartao) -> None:
        """Atualiza compras_cartao.lancamento_id para os itens da fatura
        (ADR 010, Fase 6, B6-0).

        Não recria itens nem altera outros campos — apenas grava
        lancamento_id nas linhas já existentes, casadas por
        CompraCartao.id. Itens com lancamento_id=None no objeto em
        memória são ignorados (não zera um valor já persistido).
        """
        for item in fatura.itens:
            if item.lancamento_id is None:
                continue
            orm_item = self._session.get(CompraCartaoORM, str(item.id))
            if orm_item is not None:
                orm_item.lancamento_id = str(item.lancamento_id)

    def listar_lancamento_ids_de_compras(self, empresa_id: UUID) -> set[UUID]:
        """Retorna o conjunto de lancamento_id de todas as CompraCartao
        (D7) da empresa que já têm lançamento gerado (ADR 010, Fase 6,
        B6-2).

        Usado exclusivamente para excluir compras individuais da lista
        de candidatos de MotorConciliacao — nunca via categoria, valor,
        data ou descrição. Independente de período: retorna todo o
        histórico da empresa, não apenas um intervalo — a aplicação de
        um filtro temporal (se necessário) é responsabilidade exclusiva
        de quem já filtrou a lista de lançamentos por data (o método em
        si não introduz nem pressupõe recorte temporal).
        """
        stmt = select(CompraCartaoORM.lancamento_id).where(
            CompraCartaoORM.empresa_id == str(empresa_id),
            CompraCartaoORM.lancamento_id.is_not(None),
        )
        return {
            UUID(lancamento_id)
            for lancamento_id in self._session.execute(stmt).scalars()
        }

    def _buscar_orm_por_chave(
        self, cartao_id: str, periodo_referencia: date | None
    ) -> FaturaCartaoORM | None:
        stmt = select(FaturaCartaoORM).where(
            FaturaCartaoORM.cartao_id == cartao_id,
            FaturaCartaoORM.periodo_referencia == periodo_referencia,
        )
        return self._session.execute(stmt).scalar_one_or_none()


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _cartao_para_dominio(orm: CartaoCreditoORM) -> CartaoCredito:
    return CartaoCredito(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        emissor=orm.emissor,
        final_numero=orm.final_numero,
        titular=orm.titular,
        conta_codigo=CodigoConta(orm.conta_codigo),
        guid_gnucash=orm.guid_gnucash,
        ativo=orm.ativo,
        criado_em=orm.criado_em,
    )


def _fatura_para_orm(fatura: FaturaCartao, orm: FaturaCartaoORM) -> None:
    orm.empresa_id = str(fatura.empresa_id)
    orm.cartao_id = str(fatura.cartao_id) if fatura.cartao_id else None
    orm.documento_id = str(fatura.documento_id) if fatura.documento_id else None
    orm.periodo_referencia = fatura.periodo_referencia
    orm.data_fechamento = fatura.data_fechamento
    orm.data_vencimento = fatura.data_vencimento
    orm.valor_total_declarado = fatura.valor_total_declarado.valor
    orm.status_fechamento = fatura.status_fechamento.value
    orm.criado_em = fatura.criado_em
    orm.itens = [_item_para_orm(item, str(fatura.id)) for item in fatura.itens]


def _fatura_para_dominio(orm: FaturaCartaoORM) -> FaturaCartao:
    return FaturaCartao(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        cartao_id=UUID(orm.cartao_id) if orm.cartao_id else None,
        documento_id=UUID(orm.documento_id) if orm.documento_id else None,
        periodo_referencia=orm.periodo_referencia,
        data_fechamento=orm.data_fechamento,
        data_vencimento=orm.data_vencimento,
        valor_total_declarado=Dinheiro(orm.valor_total_declarado),
        status_fechamento=StatusFechamentoFatura(orm.status_fechamento),
        criado_em=orm.criado_em,
        itens=[_item_para_dominio(item) for item in orm.itens],
    )


def _item_para_orm(item: CompraCartao, fatura_id: str) -> CompraCartaoORM:
    return CompraCartaoORM(
        id=str(item.id),
        empresa_id=str(item.empresa_id),
        fatura_id=fatura_id,
        lancamento_id=str(item.lancamento_id) if item.lancamento_id else None,
        tipo=item.tipo.value,
        estabelecimento=item.estabelecimento,
        descricao_original=item.descricao_original,
        data_compra=item.data_compra,
        valor=item.valor.valor,
        parcela_atual=item.parcela_atual,
        total_parcelas=item.total_parcelas,
        posicao_linha=item.posicao_linha,
        hash_linha=item.hash_linha,
        criado_em=item.criado_em,
    )


def _item_para_dominio(orm: CompraCartaoORM) -> CompraCartao:
    return CompraCartao(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        fatura_id=UUID(orm.fatura_id),
        lancamento_id=UUID(orm.lancamento_id) if orm.lancamento_id else None,
        tipo=TipoItemFatura(orm.tipo),
        estabelecimento=orm.estabelecimento,
        descricao_original=orm.descricao_original,
        data_compra=orm.data_compra,
        valor=Dinheiro(orm.valor),
        parcela_atual=orm.parcela_atual,
        total_parcelas=orm.total_parcelas,
        posicao_linha=orm.posicao_linha,
        hash_linha=orm.hash_linha,
        criado_em=orm.criado_em,
        confidence=None,  # não persistido nesta fase — ver Ambiguidade no relatório da Fase 4
    )
