"""Teste da migration de dados a4c7f19e2b6d (DT-CC-01 / ADR 011, B.2.2).

Simula o cenário real que a migration precisa resolver: Split já
persistido em f2b8d5e3a1c7 (empresa_id nullable, ainda não populado
por nenhum código) — insere linhas "legadas" via SQL bruto, direto no
schema, sem passar por LancamentoRepository (que já preencheria
empresa_id corretamente, mascarando o que a migration precisa fazer).
Depois roda a migration seguinte e confirma o backfill.

Não reutiliza _sessionfactory_via_alembic de test_schema_alembic_integracao.py
porque aquele helper sobe direto para "head" — este teste precisa parar
em f2b8d5e3a1c7 (antes do backfill) para inserir os dados legados.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _alembic_config(db_path: Path, monkeypatch):
    from alembic.config import Config

    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg, url


class TestBackfillSplitsEmpresaId:
    def test_backfill_popula_empresa_id_a_partir_do_lancamento_pai(
        self, tmp_path, monkeypatch
    ) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "backfill.db"
        cfg, url = _alembic_config(db_path, monkeypatch)

        # Schema parado ANTES do backfill — splits.empresa_id existe,
        # nullable, ainda não populado (estado real deixado por B.2.1).
        command.upgrade(cfg, "f2b8d5e3a1c7")

        engine = create_engine(url)
        empresa_x = "11111111-1111-1111-1111-111111111111"
        empresa_y = "22222222-2222-2222-2222-222222222222"
        with engine.begin() as conn:
            # Lancamento/Split "legados" — inseridos direto via SQL,
            # simulando dados que já existiam antes de qualquer código
            # passar a popular empresa_id (o que LancamentoRepository já
            # faz desde esta mesma unidade B.2.2 — por isso não se usa
            # o repositório aqui, senão o cenário legado nunca existiria).
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-x', :empresa_x, '2026-08-01T00:00:00', 'legado X', 0, 0, 'aprovado')"
            ), {"empresa_x": empresa_x})
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-y', :empresa_y, '2026-08-01T00:00:00', 'legado Y', 0, 0, 'aprovado')"
            ), {"empresa_y": empresa_y})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-x1', 'lanc-x', NULL, '4.1.01.001', 'debito', 10.00, 'BRL')"
            ))
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-y1', 'lanc-y', NULL, '1.1.01.002', 'credito', 10.00, 'BRL')"
            ))
        engine.dispose()

        # Confirma o estado legado antes de migrar — se isso falhar, o
        # teste não está exercitando o que promete.
        engine = create_engine(url)
        with engine.connect() as conn:
            antes = conn.execute(text("SELECT id, empresa_id FROM splits ORDER BY id")).fetchall()
        engine.dispose()
        assert [r.empresa_id for r in antes] == [None, None]

        # Roda o backfill
        command.upgrade(cfg, "a4c7f19e2b6d")

        engine = create_engine(url)
        with engine.connect() as conn:
            depois = {
                r.id: r.empresa_id
                for r in conn.execute(text("SELECT id, empresa_id FROM splits"))
            }
        engine.dispose()

        assert depois["split-x1"] == empresa_x
        assert depois["split-y1"] == empresa_y

    def test_backfill_nao_sobrescreve_empresa_id_ja_preenchido(
        self, tmp_path, monkeypatch
    ) -> None:
        """Idempotência: um Split que já chegou com empresa_id correto
        (fluxo novo, pós B.2.2) não deve ser tocado pela migration —
        a cláusula WHERE empresa_id IS NULL garante isso."""
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "backfill_idempotente.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "f2b8d5e3a1c7")

        empresa_correta = "33333333-3333-3333-3333-333333333333"
        empresa_lancamento = "44444444-4444-4444-4444-444444444444"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-z', :empresa_lancamento, '2026-08-01T00:00:00', 'z', 0, 0, 'aprovado')"
            ), {"empresa_lancamento": empresa_lancamento})
            # empresa_id já preenchido, e deliberadamente DIFERENTE do
            # lancamento pai — se o backfill sobrescrevesse tudo (sem o
            # WHERE), este teste pegaria o erro.
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-z1', 'lanc-z', :empresa_correta, '4.1.01.001', 'debito', 5.00, 'BRL')"
            ), {"empresa_correta": empresa_correta})
        engine.dispose()

        command.upgrade(cfg, "a4c7f19e2b6d")

        engine = create_engine(url)
        with engine.connect() as conn:
            valor = conn.execute(
                text("SELECT empresa_id FROM splits WHERE id = 'split-z1'")
            ).scalar_one()
        engine.dispose()
        assert valor == empresa_correta
