"""Fila de aprovação — endpoints de consulta e mutação (ADR 008, W2+W3).

GET /lancamentos/pendentes: consulta, protegida por autenticação (W2).

POST /lancamentos/{id}/aprovar e /rejeitar (W3): primeira mutação de
estado real da Interface Web. Toda a decisão de autorização (quem pode
aprovar o quê, alçada de valor, segregação de funções) passa por
PolicyEngine + Usuario — este arquivo nunca reimplementa essa lógica,
apenas traduz o resultado do domínio para HTTP (ADR 008 §9).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import get_current_user, get_session_factory
from core.audit.chain import TipoEvento
from core.domain.entities import StatusLancamento, Usuario
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.policies.engine import PolicyEngine, ResultadoPolitica

router = APIRouter(prefix="/lancamentos", tags=["lançamentos"])


def get_policy_engine() -> PolicyEngine:
    """Mesma lógica de core/cli.py — mantém o limite de aprovação
    consistente entre o pipeline automatizado e a aprovação manual via API.
    Divergir aqui criaria duas fontes de verdade para a mesma política.

    Como dependency (não singleton de módulo): lê a variável de ambiente
    a cada requisição, não uma vez na importação — evita o mesmo problema
    que CADERNETA_SECRET_KEY teve em api/auth/session.py (valor
    congelado antes de qualquer fixture de teste rodar)."""
    import os
    try:
        limite = Decimal(os.getenv("LIMITE_APROVACAO_SIMPLES", "5000.00"))
    except Exception:
        limite = Decimal("5000.00")
    return PolicyEngine(limite_aprovacao_simples=limite)


class LancamentoResumo(BaseModel):
    id: str
    data_lancamento: Optional[date]
    descricao: str
    valor_total: Decimal
    status: str
    categoria: Optional[str]


class DecisaoRequest(BaseModel):
    justificativa: Optional[str] = None


class DecisaoResponse(BaseModel):
    id: str
    status: str
    motivo: str


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


@router.post("/{lancamento_id}/aprovar", response_model=DecisaoResponse)
def aprovar(
    lancamento_id: str,
    dados: DecisaoRequest,
    usuario: Usuario = Depends(get_current_user),
    session_factory: SessionFactory = Depends(get_session_factory),
    policy_engine: PolicyEngine = Depends(get_policy_engine),
) -> DecisaoResponse:
    """Aprova um lançamento pendente.

    Justificativa opcional para aprovação rotineira, obrigatória para
    aprovação de alto valor (ADR 008 §7) — a determinação de "alto valor"
    vem inteiramente de PolicyEngine.avaliar_aprovacao() via politica_nome,
    nunca de uma comparação de limite reimplementada aqui.
    """
    with UnitOfWork(session_factory) as uow:
        lancamento = _buscar_lancamento_da_empresa(uow, lancamento_id, usuario.empresa_id)

        if lancamento.status != StatusLancamento.PENDENTE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lançamento não está pendente (status atual: "
                       f"{lancamento.status.value}).",
            )

        # Gate 0 — B3: nível desta aprovação. aprovado_por_1 já presente
        # significa que esta é a segunda chamada para um lançamento
        # DOIS_APROVADORES (a primeira nunca teria deixado o status como
        # PENDENTE se fosse UM_APROVADOR — ver Lancamento.aprovar()).
        nivel1_ja_aprovado = lancamento.aprovado_por_1 is not None
        nivel = 2 if nivel1_ja_aprovado else 1

        # Gate 0 — D1: a autoria real do lançamento (populada pelo pipeline
        # ou, no futuro, por criação humana autenticada) é propagada como
        # está — nunca fabricada como "" aqui. PolicyEngine decide o que
        # fazer com None (falha fechada) ou com uma autoria conhecida
        # (segregação de funções). aprovador_nivel1_id habilita a
        # segregação entre níveis (Gate 0 — B3): o mesmo ator não pode
        # ocupar os dois níveis de uma aprovação em cascata.
        avaliacao = policy_engine.avaliar_aprovacao(
            valor_lancamento=lancamento.valor_total.valor,
            aprovador=usuario,
            criador_id=lancamento.criado_por,
            aprovador_nivel1_id=lancamento.aprovado_por_1 if nivel1_ja_aprovado else None,
        )

        if avaliacao.resultado != ResultadoPolitica.PERMITIDO:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=avaliacao.motivo,
            )

        if avaliacao.politica_nome == "aprovacao_alto_valor" and not dados.justificativa:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Justificativa obrigatória para aprovação de alto valor.",
            )

        # Gate 0 — B3: a mutação de estado passa a ser feita pelo agregado
        # (Lancamento.aprovar()), não pelo router. É essa delegação que
        # faz DOIS_APROVADORES permanecer PENDENTE após o nível 1 —
        # antes, o router marcava APROVADO incondicionalmente aqui,
        # ignorando nivel_aprovacao por completo (achado reproduzido no
        # Gate 0 antes desta correção).
        lancamento.aprovar(str(usuario.id), nivel=nivel)
        uow.lancamentos.salvar(lancamento)

        aprovacao_completa = lancamento.status == StatusLancamento.APROVADO
        motivo_resposta = avaliacao.motivo
        if not aprovacao_completa:
            motivo_resposta = (
                f"{avaliacao.motivo} Primeira aprovação registrada — "
                f"aguardando segundo aprovador (nível 2)."
            )

        uow.audit.registrar(
            tipo=TipoEvento.LANCAMENTO_APROVADO,
            payload={
                "papel": usuario.papel,
                "justificativa": dados.justificativa,
                "politica_aplicada": avaliacao.politica_nome,
                "motivo": avaliacao.motivo,
                "nivel_aprovacao_aplicado": nivel,
                "aprovacao_completa": aprovacao_completa,
            },
            usuario=str(usuario.id),
            empresa_id=str(usuario.empresa_id),
            lancamento_id=str(lancamento.id),
        )
        uow.commit()

    return DecisaoResponse(
        id=str(lancamento.id),
        status=lancamento.status.value,
        motivo=motivo_resposta,
    )


@router.post("/{lancamento_id}/rejeitar", response_model=DecisaoResponse)
def rejeitar(
    lancamento_id: str,
    dados: DecisaoRequest,
    usuario: Usuario = Depends(get_current_user),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> DecisaoResponse:
    """Rejeita um lançamento pendente. Justificativa sempre obrigatória
    (ADR 008 §7) — diferente da aprovação, rejeição nunca é opcional."""
    if not dados.justificativa:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Justificativa obrigatória para rejeição.",
        )

    with UnitOfWork(session_factory) as uow:
        lancamento = _buscar_lancamento_da_empresa(uow, lancamento_id, usuario.empresa_id)

        if lancamento.status != StatusLancamento.PENDENTE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lançamento não está pendente (status atual: "
                       f"{lancamento.status.value}).",
            )

        if not usuario.pode_aprovar():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Papel '{usuario.papel}' não tem permissão para "
                       f"rejeitar lançamentos.",
            )

        lancamento.status = StatusLancamento.REJEITADO
        uow.lancamentos.salvar(lancamento)

        uow.audit.registrar(
            tipo=TipoEvento.LANCAMENTO_REJEITADO,
            payload={
                "papel": usuario.papel,
                "justificativa": dados.justificativa,
            },
            usuario=str(usuario.id),
            empresa_id=str(usuario.empresa_id),
            lancamento_id=str(lancamento.id),
        )
        uow.commit()

    return DecisaoResponse(
        id=str(lancamento.id),
        status=lancamento.status.value,
        motivo=dados.justificativa,
    )


def _buscar_lancamento_da_empresa(uow, lancamento_id: str, empresa_id):
    """Busca um lançamento garantindo que pertence à empresa do usuário
    autenticado — nunca confia em empresa_id vindo do cliente. 404 tanto
    para 'não existe' quanto para 'existe mas é de outra empresa' — não
    revela a uma empresa que o ID pertence a outra."""
    try:
        from uuid import UUID
        lanc_uuid = UUID(lancamento_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado.")

    lancamento = uow.lancamentos.buscar_por_id(lanc_uuid)
    if lancamento is None or lancamento.empresa_id != empresa_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado.")

    return lancamento
