"""DocumentoRepository — persistência de Documento.

Responsabilidade: converter entre Documento (domínio) e DocumentoORM (banco)
e executar queries relacionadas a documentos.

Regra: o repositório nunca retorna ORM diretamente — apenas entidades de domínio.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.domain.entities import (
    CNPJ,
    ConfidenceScore,
    Dinheiro,
    Documento,
    FonteExtracao,
    MetadadosNFe,
    NaturezaLancamento,
    TipoDocumento,
)
from core.infra.db.models import DocumentoORM


class DocumentoRepository:
    """Repositório de Documento — operações de persistência e consulta."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Escrita ──────────────────────────────────────────────────────────

    def salvar(self, documento: Documento) -> None:
        """Persiste ou atualiza um Documento."""
        orm = self._session.get(DocumentoORM, str(documento.id))
        if orm is None:
            orm = DocumentoORM(id=str(documento.id))
            self._session.add(orm)
        _para_orm(documento, orm)

    # ── Leitura ──────────────────────────────────────────────────────────

    def buscar_por_id(self, documento_id: UUID) -> Optional[Documento]:
        orm = self._session.get(DocumentoORM, str(documento_id))
        return _para_dominio(orm) if orm else None

    def buscar_por_hash(self, hash_sha256: str, empresa_id: UUID) -> Optional[Documento]:
        stmt = select(DocumentoORM).where(
            DocumentoORM.hash_sha256 == hash_sha256,
            DocumentoORM.empresa_id == str(empresa_id),
        )
        orm = self._session.execute(stmt).scalar_one_or_none()
        return _para_dominio(orm) if orm else None

    def listar_por_empresa(
        self,
        empresa_id: UUID,
        precisa_revisao: Optional[bool] = None,
        tipo: Optional[TipoDocumento] = None,
        limit: int = 100,
    ) -> list[Documento]:
        stmt = select(DocumentoORM).where(
            DocumentoORM.empresa_id == str(empresa_id)
        )
        if precisa_revisao is not None:
            stmt = stmt.where(DocumentoORM.precisa_revisao == precisa_revisao)
        if tipo is not None:
            stmt = stmt.where(DocumentoORM.tipo == tipo.value)
        stmt = stmt.limit(limit).order_by(DocumentoORM.data_processamento.desc())
        return [_para_dominio(orm) for orm in self._session.execute(stmt).scalars()]

    def existe_hash(self, hash_sha256: str, empresa_id: UUID) -> bool:
        stmt = select(DocumentoORM.id).where(
            DocumentoORM.hash_sha256 == hash_sha256,
            DocumentoORM.empresa_id == str(empresa_id),
        )
        return self._session.execute(stmt).first() is not None

    def deletar(self, documento_id: UUID) -> bool:
        orm = self._session.get(DocumentoORM, str(documento_id))
        if orm is None:
            return False
        self._session.delete(orm)
        return True


# =============================================================
# MAPEAMENTO DOMÍNIO ↔ ORM
# =============================================================

def _para_orm(doc: Documento, orm: DocumentoORM) -> None:
    """Copia campos do Documento de domínio para o ORM (mutação in-place)."""
    orm.empresa_id = str(doc.empresa_id)
    orm.hash_sha256 = doc.hash_sha256
    orm.nome_arquivo = doc.nome_arquivo
    orm.tipo = doc.tipo.value
    orm.fonte_extracao = doc.fonte_extracao.value
    orm.cnpj_emitente = doc.cnpj_emitente.numero if doc.cnpj_emitente else None
    orm.nome_emitente = doc.nome_emitente
    orm.data_emissao = doc.data_emissao
    orm.data_vencimento = doc.data_vencimento
    orm.data_processamento = doc.data_processamento
    orm.valor_total = doc.valor_total.valor if doc.valor_total else None
    orm.valor_desconto = doc.valor_desconto.valor
    orm.valor_liquido = doc.valor_liquido.valor if doc.valor_liquido else None
    orm.chave_acesso = doc.chave_acesso
    orm.numero_documento = doc.numero_documento
    orm.cfop = doc.cfop
    orm.natureza_operacao = doc.natureza_operacao.value if doc.natureza_operacao else None
    orm.confidence_minima = doc.confidence_minima if doc.confidence_scores else None
    orm.precisa_revisao = doc.precisa_revisao
    orm.motivo_revisao = doc.motivo_revisao
    orm.metadados_nfe = _metadados_para_dict(doc.metadados_nfe)


def _para_dominio(orm: DocumentoORM) -> Documento:
    """Reconstrói Documento de domínio a partir do ORM."""
    cnpj = None
    if orm.cnpj_emitente:
        try:
            cnpj = CNPJ(orm.cnpj_emitente)
        except ValueError:
            pass

    scores = []
    if orm.confidence_minima is not None:
        scores = [ConfidenceScore(float(orm.confidence_minima), "persistido")]

    return Documento(
        id=UUID(orm.id),
        empresa_id=UUID(orm.empresa_id),
        hash_sha256=orm.hash_sha256,
        nome_arquivo=orm.nome_arquivo,
        tipo=TipoDocumento(orm.tipo),
        fonte_extracao=FonteExtracao(orm.fonte_extracao),
        cnpj_emitente=cnpj,
        nome_emitente=orm.nome_emitente,
        data_emissao=orm.data_emissao,
        data_vencimento=orm.data_vencimento,
        data_processamento=orm.data_processamento,
        valor_total=Dinheiro(orm.valor_total) if orm.valor_total is not None else None,
        valor_desconto=Dinheiro(orm.valor_desconto or Decimal("0")),
        valor_liquido=Dinheiro(orm.valor_liquido) if orm.valor_liquido is not None else None,
        chave_acesso=orm.chave_acesso,
        numero_documento=orm.numero_documento,
        cfop=orm.cfop,
        natureza_operacao=NaturezaLancamento(orm.natureza_operacao)
            if orm.natureza_operacao else None,
        confidence_scores=scores,
        precisa_revisao=orm.precisa_revisao,
        motivo_revisao=orm.motivo_revisao,
        metadados_nfe=_metadados_de_dict(orm.metadados_nfe),
    )


def _metadados_para_dict(meta: Optional[MetadadosNFe]) -> Optional[dict]:
    if meta is None:
        return None
    return {
        "chave_acesso": meta.chave_acesso,
        "finalidade": meta.finalidade,
        "natureza_operacao_texto": meta.natureza_operacao_texto,
        "cfop_itens": list(meta.cfop_itens),
        "ncm_itens": list(meta.ncm_itens),
        "cst_icms": meta.cst_icms,
        "cnpj_destinatario": meta.cnpj_destinatario.numero
            if meta.cnpj_destinatario else None,
        "valor_icms": str(meta.valor_icms.valor),
        "valor_pis": str(meta.valor_pis.valor),
        "valor_cofins": str(meta.valor_cofins.valor),
        "valor_ipi": str(meta.valor_ipi.valor),
    }


def _metadados_de_dict(d: Optional[dict]) -> Optional[MetadadosNFe]:
    if d is None:
        return None
    cnpj_dest = None
    if d.get("cnpj_destinatario"):
        try:
            cnpj_dest = CNPJ(d["cnpj_destinatario"])
        except ValueError:
            pass
    return MetadadosNFe(
        chave_acesso=d.get("chave_acesso", ""),
        finalidade=d.get("finalidade", 1),
        natureza_operacao_texto=d.get("natureza_operacao_texto", ""),
        cfop_itens=tuple(d.get("cfop_itens", [])),
        ncm_itens=tuple(d.get("ncm_itens", [])),
        cst_icms=d.get("cst_icms"),
        cnpj_destinatario=cnpj_dest,
        valor_icms=Dinheiro(Decimal(d.get("valor_icms", "0"))),
        valor_pis=Dinheiro(Decimal(d.get("valor_pis", "0"))),
        valor_cofins=Dinheiro(Decimal(d.get("valor_cofins", "0"))),
        valor_ipi=Dinheiro(Decimal(d.get("valor_ipi", "0"))),
    )
