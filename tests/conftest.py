"""Fixtures globais para os testes do Caderneta v0.2."""

import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def configurar_env_teste(monkeypatch, tmp_path):
    """Isola os testes do ambiente real."""
    monkeypatch.setenv("CADERNETA_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://caderneta:caderneta_dev@localhost:5432/caderneta_test")
