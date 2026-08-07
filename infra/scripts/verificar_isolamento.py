#!/usr/bin/env python3
"""Verifica as regras de isolamento entre core/, ai/ e api/.

Executa como parte do CI. Falha se qualquer regra abaixo for violada:

- core/ nunca importa ai/                  (ADR 001)
- core/ nunca importa api/                 (ADR 008 — core não conhece a web)
- api/ nunca importa ai/ diretamente       (ADR 008 — mesma disciplina do core/)
- ai/ nunca importa api/                   (ADR 003/008 — ai/ só conhece core/ports)

Estas são as garantias arquiteturais centrais do Caderneta.
"""

import ast
import sys
from pathlib import Path

# (diretório escaneado, prefixo de import proibido, referência do ADR)
REGRAS = [
    ("core", "ai", "ADR 001"),
    ("core", "api", "ADR 008"),
    ("api", "ai", "ADR 008"),
    ("ai", "api", "ADR 003/008"),
]


def _nomes_importados(no: ast.AST) -> list[tuple[str, int]]:
    """Retorna [(nome_do_modulo, linha)] para um nó Import/ImportFrom."""
    resultado = []
    if isinstance(no, ast.Import):
        for alias in no.names:
            resultado.append((alias.name, no.lineno))
    elif isinstance(no, ast.ImportFrom):
        resultado.append((no.module or "", no.lineno))
    return resultado


def verificar_isolamento(raiz: Path) -> list[str]:
    """Retorna lista de violações encontradas, cobrindo todas as REGRAS."""
    violacoes = []

    for dir_escaneado, prefixo_proibido, adr in REGRAS:
        alvo = raiz / dir_escaneado
        if not alvo.exists():
            continue

        for arquivo in alvo.rglob("*.py"):
            try:
                arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            except SyntaxError:
                continue

            for no in ast.walk(arvore):
                if not isinstance(no, (ast.Import, ast.ImportFrom)):
                    continue
                for nome, linha in _nomes_importados(no):
                    if nome == prefixo_proibido or nome.startswith(f"{prefixo_proibido}."):
                        violacoes.append(
                            f"{arquivo.relative_to(raiz)}: import de '{nome}' "
                            f"(linha {linha}) — {dir_escaneado}/ nunca importa "
                            f"{prefixo_proibido}/ ({adr})"
                        )

    return violacoes


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parent.parent.parent
    violacoes = verificar_isolamento(raiz)

    if violacoes:
        print("❌ VIOLAÇÕES DE ISOLAMENTO DETECTADAS:")
        for v in violacoes:
            print(f"  • {v}")
        print(
            "\nRegras violadas — core/ nunca importa ai/ nem api/; "
            "api/ nunca importa ai/; ai/ nunca importa api/. "
            "Ver ADR 001, ADR 003 e ADR 008."
        )
        sys.exit(1)
    else:
        print("✅ Isolamento core/ai/api verificado — nenhuma violação encontrada.")
        sys.exit(0)
