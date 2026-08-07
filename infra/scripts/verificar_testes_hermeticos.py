#!/usr/bin/env python3
"""Verifica que tests/unit/ não depende de infraestrutura externa.

Executa como parte do CI. Falha se qualquer arquivo em tests/unit/
importar bibliotecas de rede/infra externa, ou construir uma string
de conexão não-SQLite (ex.: PostgreSQL real).

SQLite em memória é a exceção explicitamente permitida (ADR 006,
seção "Convenções de teste") — é hermético (sem sockets, sem disco)
e mantém a suíte rápida. tests/integration/ não tem essa restrição,
pois depende de fato de Docker Compose (Postgres, Redis).

Complementa a proteção em runtime via pytest-socket (tests/unit/conftest.py),
que bloqueia qualquer chamada de socket durante a execução dos testes.
"""

import ast
import re
import sys
from pathlib import Path

# Bibliotecas que indicam dependência de infraestrutura externa —
# não devem aparecer em nenhum import dentro de tests/unit/.
LIBS_PROIBIDAS = {
    "psycopg",
    "psycopg2",
    "docker",
    "redis",
    "requests",
    "httpx",
    "boto3",
    "pymongo",
}

# Padrões de string de conexão que indicam banco externo real.
PADROES_CONEXAO_PROIBIDOS = [
    re.compile(r"postgresql(\+\w+)?://"),
    re.compile(r"mysql(\+\w+)?://"),
    re.compile(r"redis://"),
]


def verificar_testes_hermeticos(raiz: Path) -> list[str]:
    """Retorna lista de violações encontradas em tests/unit/."""
    violacoes = []
    tests_unit_dir = raiz / "tests" / "unit"

    if not tests_unit_dir.exists():
        return violacoes

    for arquivo in tests_unit_dir.rglob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")

        try:
            arvore = ast.parse(texto)
        except SyntaxError:
            continue

        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    raiz_modulo = alias.name.split(".")[0]
                    if raiz_modulo in LIBS_PROIBIDAS:
                        violacoes.append(
                            f"{arquivo.relative_to(raiz)}: "
                            f"import {alias.name} (linha {no.lineno}) — "
                            f"biblioteca de infraestrutura externa proibida em tests/unit/"
                        )

            elif isinstance(no, ast.ImportFrom):
                modulo = (no.module or "").split(".")[0]
                if modulo in LIBS_PROIBIDAS:
                    violacoes.append(
                        f"{arquivo.relative_to(raiz)}: "
                        f"from {no.module} import ... (linha {no.lineno}) — "
                        f"biblioteca de infraestrutura externa proibida em tests/unit/"
                    )

        for numero_linha, linha in enumerate(texto.splitlines(), start=1):
            for padrao in PADROES_CONEXAO_PROIBIDOS:
                if padrao.search(linha):
                    violacoes.append(
                        f"{arquivo.relative_to(raiz)}:{numero_linha}: "
                        f"string de conexão não-SQLite detectada — "
                        f"tests/unit/ só permite SQLite em memória"
                    )

    return violacoes


if __name__ == "__main__":
    raiz = Path(__file__).parent.parent.parent
    violacoes = verificar_testes_hermeticos(raiz)

    if violacoes:
        print("❌ VIOLAÇÕES DE HERMETICIDADE EM tests/unit/ DETECTADAS:")
        for v in violacoes:
            print(f"  • {v}")
        print(
            "\ntests/unit/ não pode depender de infraestrutura externa "
            "(Postgres real, Docker, Redis, rede) — veja ADR 006. "
            "Testes que precisam disso pertencem a tests/integration/."
        )
        sys.exit(1)
    else:
        print("✅ Hermeticidade de tests/unit/ verificada — nenhuma violação encontrada.")
        sys.exit(0)
