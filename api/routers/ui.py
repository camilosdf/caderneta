"""Router de UI — rotas que servem HTML (Jinja2 + HTMX, ADR 008 W4).

Separado de api/routers/lancamentos.py (que serve JSON puro para a API)
para manter clara a fronteira: lancamentos.py é API, ui.py é apresentação.
Ambos dependem dos mesmos use cases e repositórios — nenhuma lógica de
negócio mora aqui, apenas a tradução de resultado para HTML.

GET /login       → página de login (isenta de auth, na lista fechada ADR 008 §8)
GET /fila        → página da fila de aprovação
GET /ui/fila/linhas  → fragmento HTMX (swap parcial)
POST /login (HTML) → já implementado em auth.py; este router trata só GETs de UI
"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from api.dependencies import get_current_user, get_session_factory, get_templates
from core.domain.entities import StatusLancamento, Usuario
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

router = APIRouter(tags=["ui"])


# ── Login (isenta de auth — lista fechada ADR 008 §8) ────────────────

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> HTMLResponse:
    templates = get_templates()
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"usuario": None, "erro": None},
    )


# ── Fila de aprovação ────────────────────────────────────────────────

@router.get("/fila", response_class=HTMLResponse, include_in_schema=False)
def fila_page(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
) -> HTMLResponse:
    """Página da fila — o conteúdo da tabela é carregado via HTMX após o load."""
    templates = get_templates()
    return templates.TemplateResponse(
        request=request,
        name="lancamentos/fila.html",
        context={"usuario": usuario},
    )


@router.get("/ui/fila/linhas", response_class=HTMLResponse, include_in_schema=False)
def fila_linhas(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> HTMLResponse:
    """Fragmento HTMX — retorna somente as linhas da tabela, não a página inteira.
    Chamado por hx-get="/ui/fila/linhas" no template fila.html após o load."""
    templates = get_templates()

    with UnitOfWork(session_factory) as uow:
        lancamentos_raw = uow.lancamentos.listar_por_empresa(
            usuario.empresa_id,
            status=StatusLancamento.PENDENTE,
        )

    lancamentos = [
        {
            "id": str(l.id),
            "data_lancamento": l.data_lancamento,
            "descricao": l.descricao,
            "valor_total": l.valor_total.valor,
            "status": l.status.value,
            "categoria": l.categoria,
        }
        for l in lancamentos_raw
    ]

    return templates.TemplateResponse(
        request=request,
        name="lancamentos/_linhas.html",
        context={"usuario": usuario, "lancamentos": lancamentos},
    )


# ── Redirecionamento raiz ────────────────────────────────────────────

@router.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    return RedirectResponse(url="/fila")
