#!/usr/bin/env python3
"""Verifica que core/ nunca importa ai/.

Executa como parte do CI. Falha se qualquer módulo em core/ importar ai/.
Esta é a garantia arquitetural central do Caderneta (ADR 001).
"""

import ast
import sys
from pathlib import Path


def verificar_isolamento(raiz: Path) -> list[str]:
    """Retorna lista de violações encontradas."""
    violacoes = []
    core_dir = raiz / "core"

    for arquivo in core_dir.rglob("*.py"):
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    if alias.name.startswith("ai.") or alias.name == "ai":
                        violacoes.append(
                            f"{arquivo.relative_to(raiz)}: "
                            f"import {alias.name} (linha {no.lineno})"
                        )

            elif isinstance(no, ast.ImportFrom):
                modulo = no.module or ""
                if modulo.startswith("ai.") or modulo == "ai":
                    violacoes.append(
                        f"{arquivo.relative_to(raiz)}: "
                        f"from {modulo} import ... (linha {no.lineno})"
                    )

    return violacoes


if __name__ == "__main__":
    raiz = Path(__file__).parent.parent
    violacoes = verificar_isolamento(raiz)

    if violacoes:
        print("❌ VIOLAÇÕES DE ISOLAMENTO CORE/AI DETECTADAS:")
        for v in violacoes:
            print(f"  • {v}")
        print("\nO core/ nunca deve importar ai/ — veja ADR 001.")
        sys.exit(1)
    else:
        print("✅ Isolamento Core/AI verificado — nenhuma violação encontrada.")
        sys.exit(0)
