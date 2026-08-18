"""Teste da migration de schema c9d1f6a3e8b2 (DT-CC-01 / ADR 011, B.2.4).

Mesmo padrão de test_backfill_splits_empresa_id.py e
test_backfill_cadastro_contas_em_uso.py: insere dados via SQL bruto
direto no schema parado ANTES desta migration (b7e4a2c9f1d3 — head de
B.2.3), simulando os dois cenários de órfão que a migration precisa
recusar (SRE/QA — Plano B.2.4, "migration defensiva"), e confirma que
ela aborta com RuntimeError em vez de aplicar um NOT NULL/FK
parcialmente íntegro. Confirma também o caminho feliz (dados limpos) e
o downgrade.
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


class TestMigrationFkCompostaAbortaEmOrfaos:
    def test_aborta_se_existe_split_com_empresa_id_null(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "orfao_null.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "b7e4a2c9f1d3")

        empresa = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-1', :empresa, '2026-08-01T00:00:00', 'x', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            # empresa_id NULL — simula backfill (a4c7f19e2b6d) incompleto,
            # mesmo já tendo passado por essa migration (cenário só
            # possível via SQL bruto, mas é exatamente o que a checagem
            # defensiva existe para pegar).
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-1', 'lanc-1', NULL, '4.1.01.001', 'debito', 10.00, 'BRL')"
            ))
        engine.dispose()

        with pytest.raises(RuntimeError, match="empresa_id NULL"):
            command.upgrade(cfg, "c9d1f6a3e8b2")

    def test_aborta_se_existe_split_com_conta_nao_cadastrada(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "orfao_fk.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "b7e4a2c9f1d3")

        empresa = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-2', :empresa, '2026-08-01T00:00:00', 'y', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            # empresa_id preenchido, mas conta_codigo nunca cadastrado em
            # contas_contabeis — simula cadastro (b7e4a2c9f1d3) incompleto
            # (só possível via SQL bruto: a migration b7e4a2c9f1d3 já
            # cobriria isso se o split existisse antes dela rodar).
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-2', 'lanc-2', :empresa, '9.9.99.999', 'debito', 10.00, 'BRL')"
            ), {"empresa": empresa})
        engine.dispose()

        with pytest.raises(RuntimeError, match="não cadastrado"):
            command.upgrade(cfg, "c9d1f6a3e8b2")


class TestMigrationFkCompostaCaminhoFeliz:
    def test_dados_limpos_migram_sem_erro(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "limpo.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "b7e4a2c9f1d3")

        empresa = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO contas_contabeis (id, empresa_id, codigo, nome, tipo, "
                "natureza, permite_lancamento, centro_custo_obrigatorio, versao) VALUES "
                "('cc-1', :empresa, '4.1.01.001', 'Despesa', '', 'debito', 1, 0, 1)"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-3', :empresa, '2026-08-01T00:00:00', 'z', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-3', 'lanc-3', :empresa, '4.1.01.001', 'debito', 10.00, 'BRL')"
            ), {"empresa": empresa})
        engine.dispose()

        command.upgrade(cfg, "c9d1f6a3e8b2")  # não deve levantar

        engine = create_engine(url)
        with engine.connect() as conn:
            empresa_id_col = conn.execute(
                text("SELECT empresa_id FROM splits WHERE id = 'split-3'")
            ).scalar_one()
        engine.dispose()
        assert empresa_id_col == empresa

    def test_downgrade_remove_not_null_e_fk(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "downgrade.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "b7e4a2c9f1d3")

        # Após o downgrade, empresa_id volta a aceitar NULL — se a FK
        # ainda estivesse ativa, este INSERT (conta não cadastrada)
        # falharia mesmo sem a checagem de NOT NULL.
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-4', 'dddddddd-dddd-dddd-dddd-dddddddddddd', "
                "'2026-08-01T00:00:00', 'w', 0, 0, 'aprovado')"
            ))
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('split-4', 'lanc-4', NULL, '0.0.00.000', 'debito', 1.00, 'BRL')"
            ))
        engine.dispose()
