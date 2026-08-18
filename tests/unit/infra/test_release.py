"""Testes de infra/scripts/release.py — Gate 0, item B1.

Antes desta correção, o script apenas imprimia um lembrete para o
operador registrar manualmente o evento VERSAO_HOMOLOGADA — nunca
chamava uow.audit.registrar(). Estes testes cobrem: o evento existe no
catálogo, é de fato emitido e persistido, falha fechada quando não há
DATABASE_URL, e --dry-run não grava nada (nem arquivos, nem auditoria).

release.py não é um pacote Python normal (é um script standalone que
insere a raiz do projeto em sys.path) — importado aqui via importlib,
replicando exatamente como ele é executado em produção.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from core.audit.chain import TipoEvento
from core.infra.db import SessionFactory
from core.versao import Versao

_SCRIPT_PATH = Path(__file__).parents[3] / "infra" / "scripts" / "release.py"


@pytest.fixture
def release_module():
    spec = importlib.util.spec_from_file_location("release_script_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sf(monkeypatch, tmp_path) -> SessionFactory:
    db_path = tmp_path / "release_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    factory = SessionFactory(f"sqlite:///{db_path}")
    factory.criar_tabelas()
    return factory


class TestTipoEventoVersaoHomologada:
    def test_evento_existe_no_catalogo(self):
        assert TipoEvento.VERSAO_HOMOLOGADA == "VERSAO_HOMOLOGADA"


class TestRegistrarHomologacao:
    def test_registra_evento_na_trilha(self, release_module, sf) -> None:
        nova = Versao(1, 0, 0)
        release_module.registrar_homologacao(nova)

        # VERSAO_HOMOLOGADA é evento de sistema, sem empresa_id —
        # AuditRepository.listar_por_empresa() exige empresa_id, então não
        # serve para eventos globais; consulta direta via sessão.
        from core.infra.db.models import AuditEventoORM
        from sqlalchemy import select
        with sf.session() as session:
            orms = session.execute(
                select(AuditEventoORM).where(AuditEventoORM.tipo == "VERSAO_HOMOLOGADA")
            ).scalars().all()

        assert len(orms) == 1
        assert orms[0].payload["versao_pep440"] == "1.0.0"
        assert orms[0].payload["e_producao"] is True
        assert orms[0].hash_proprio  # hash chain calculado

    def test_falha_fechada_sem_database_url(self, release_module, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        nova = Versao(1, 0, 0)

        with pytest.raises(SystemExit) as exc:
            release_module.registrar_homologacao(nova)
        assert exc.value.code == 1


class TestMainDryRunNaoRegistraNada:
    def test_producao_dry_run_nao_toca_banco(
        self, release_module, monkeypatch, tmp_path,
    ) -> None:
        """--producao --dry-run não deve exigir DATABASE_URL nem gravar
        nada — se registrar_homologacao() fosse chamada aqui sem
        DATABASE_URL, o teste falharia com SystemExit."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("builtins.input", lambda *_: "CONFIRMO")
        monkeypatch.setattr(
            sys, "argv",
            ["release.py", "--producao", "--dry-run"],
        )

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "0.999.0"\n')
        monkeypatch.setattr(release_module, "ROOT", tmp_path)

        # Não deve levantar SystemExit(1) por falta de DATABASE_URL —
        # dry-run precisa retornar antes de chegar em registrar_homologacao().
        release_module.main()