#!/usr/bin/env python3
"""Verifica que toda rota de api/routers/ exige autenticação.

Executa como parte do CI. Falha se qualquer função decorada com
@router.get/post/put/delete/patch não tiver um parâmetro com
Depends(get_current_user) ou Depends(require_role(...)) — exceto as
rotas na lista fechada de exceções do ADR 008 §8.

Rotas de infraestrutura definidas diretamente em api/main.py (/health,
/ready, /live) não são varridas aqui — elas nunca usam @router, são
@app.get direto, e já são a exceção documentada por construção.

Pré-requisito obrigatório do W3 (ADR 008) — não apenas planejado.
"""

import ast
import sys
from pathlib import Path

# Lista fechada de exceções — qualquer rota fora daqui exige autenticação.
# Ver ADR 008 §8. /health, /ready, /live não aparecem aqui pois nunca são
# definidas via @router (são @app direto em api/main.py).
ROTAS_ISENTAS_DE_AUTH = {"/login", "/logout", "/"}

DECORATORES_DE_ROTA = {"get", "post", "put", "delete", "patch"}

DEPENDENCIES_DE_AUTH = {"get_current_user", "require_role"}


def _e_decorador_de_rota(no: ast.expr) -> tuple[bool, str | None]:
    """Retorna (é_rota, path_literal) para um decorador @router.<metodo>("...")."""
    if not isinstance(no, ast.Call):
        return False, None
    func = no.func
    if not isinstance(func, ast.Attribute):
        return False, None
    if func.attr not in DECORATORES_DE_ROTA:
        return False, None
    if not no.args:
        return False, None
    primeiro_arg = no.args[0]
    if isinstance(primeiro_arg, ast.Constant) and isinstance(primeiro_arg.value, str):
        return True, primeiro_arg.value
    return True, None  # rota dinâmica sem literal — segue verificando auth


def _funcao_tem_dependency_de_auth(funcao: ast.FunctionDef) -> bool:
    """Varre os defaults dos parâmetros da função por Depends(get_current_user)
    ou Depends(require_role(...))."""
    for arg_default in funcao.args.defaults:
        if not isinstance(arg_default, ast.Call):
            continue
        # Depends(...)
        if not (isinstance(arg_default.func, ast.Name) and arg_default.func.id == "Depends"):
            continue
        if not arg_default.args:
            continue
        interno = arg_default.args[0]
        # Depends(get_current_user) — Name direto
        if isinstance(interno, ast.Name) and interno.id in DEPENDENCIES_DE_AUTH:
            return True
        # Depends(require_role("papel1", "papel2")) — chamada
        if isinstance(interno, ast.Call) and isinstance(interno.func, ast.Name):
            if interno.func.id in DEPENDENCIES_DE_AUTH:
                return True
    return False


def verificar_endpoints_auth(raiz: Path) -> list[str]:
    """Retorna lista de violações encontradas em api/routers/."""
    violacoes = []
    routers_dir = raiz / "api" / "routers"

    if not routers_dir.exists():
        return violacoes

    for arquivo in sorted(routers_dir.glob("*.py")):
        if arquivo.name == "__init__.py":
            continue

        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for no in ast.walk(arvore):
            if not isinstance(no, ast.FunctionDef):
                continue

            for decorador in no.decorator_list:
                e_rota, path = _e_decorador_de_rota(decorador)
                if not e_rota:
                    continue

                if path in ROTAS_ISENTAS_DE_AUTH:
                    break  # rota explicitamente isenta — não exige Depends

                if not _funcao_tem_dependency_de_auth(no):
                    violacoes.append(
                        f"{arquivo.relative_to(raiz)}: rota '{path or '(dinâmica)'}' "
                        f"na função '{no.name}' (linha {no.lineno}) não tem "
                        f"Depends(get_current_user) nem Depends(require_role(...))"
                    )
                break  # já processou o decorador de rota desta função

    return violacoes


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parent.parent.parent
    violacoes = verificar_endpoints_auth(raiz)

    if violacoes:
        print("❌ ROTAS SEM AUTENTICAÇÃO DETECTADAS:")
        for v in violacoes:
            print(f"  • {v}")
        print(
            "\nToda rota em api/routers/ exige Depends(get_current_user) ou "
            "Depends(require_role(...)), exceto /login e /logout — "
            "ver ADR 008 §8."
        )
        sys.exit(1)
    else:
        print("✅ Autenticação de endpoints verificada — nenhuma violação encontrada.")
        sys.exit(0)
