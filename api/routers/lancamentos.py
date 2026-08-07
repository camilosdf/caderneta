"""Fila de aprovação — endpoint só-leitura (ADR 008, W2).

GET /lancamentos/pendentes é a primeira rota de consulta real da
Interface Web. Protegida por autenticação (ADR 008 §8 — toda rota exige
sessão, sem exceção fora da lista fechada). Sem restrição de papel: a
visibilidade da fila é aberta a qualquer usuário autenticado da empresa;
a ação de aprovar/rejeitar (papel restrito) é escopo do W3.

empresa_id vem exclusivamente da identidade autenticada (usuario.empresa_id),
nunca de query string — mesmo corolário anti-falsificação do ADR 008 §9:
o servidor nunca confia em dados de escopo enviados pelo cliente.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_current_user, get_session_factory
from core.domain.entities import StatusLancamento, Usuario
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

router = APIRouter(prefix="/lancamentos", tags=["lançamentos"])


class LancamentoResumo(BaseModel):
    id: str
    data_lancamento: Optional[date]
    descricao: str
    valor_total: Decimal
    status: str
    categoria: Optional[str]


@router.get("/pendentes", response_model=list[LancamentoResumo])
def listar_pendentes(
    usuario: Usuario = Depends(get_current_user),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> list[LancamentoResumo]:
    """Lista lançamentos com status PENDENTE da empresa do usuário logado."""
    with UnitOfWork(session_factory) as uow:
        lancamentos = uow.lancamentos.listar_por_empresa(
            usuario.empresa_id,
            status=StatusLancamento.PENDENTE,
        )

    return [
        LancamentoResumo(
            id=str(l.id),
            data_lancamento=l.data_lancamento,
            descricao=l.descricao,
            valor_total=l.valor_total.valor,
            status=l.status.value,
            categoria=l.categoria,
        )
        for l in lancamentos
    ]
