"""Teste da migration de dados b7e4a2c9f1d3 (DT-CC-01 / ADR 011, B.2.3).

Mesmo padrão de test_backfill_splits_empresa_id.py: insere dados
"legados" via SQL bruto direto no schema parado ANTES desta migration
(a4c7f19e2b6d — splits.empresa_id já populado por B.2.2, mas nenhuma
conta ainda cadastrada), depois roda a migration e confirma o
cadastro retroativo.
"""

from pathlib import Path

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


_NOME_PLACEHOLDER = "(pendente de revisão — cadastrada automaticamente por B.2.3)"


class TestBackfillCadastroContasEmUso:
    def test_cadastra_contas_distintas_de_splits_e_cartoes(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "cadastro.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "a4c7f19e2b6d")

        empresa = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-1', :empresa, '2026-08-01T00:00:00', 'x', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            # Dois splits com contas distintas — 4.1.01.001 usada duas
            # vezes (não deve gerar cadastro duplicado).
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('s1', 'lanc-1', :empresa, '4.1.01.001', 'debito', 10.00, 'BRL')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('s2', 'lanc-1', :empresa, '1.1.01.002', 'credito', 10.00, 'BRL')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('s3', 'lanc-1', :empresa, '4.1.01.001', 'debito', 5.00, 'BRL')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO cartoes_credito (id, empresa_id, emissor, final_numero, "
                "titular, conta_codigo, ativo, criado_em) VALUES "
                "('cc1', :empresa, 'Nubank', '1234', 'Camilo', '2.1.05.001', "
                "1, '2026-08-01T00:00:00')"
            ), {"empresa": empresa})
        engine.dispose()

        command.upgrade(cfg, "b7e4a2c9f1d3")

        engine = create_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT empresa_id, codigo, nome, permite_lancamento FROM contas_contabeis "
                "ORDER BY codigo"
            )).fetchall()
        engine.dispose()

        codigos = [r.codigo for r in rows]
        assert codigos == ["1.1.01.002", "2.1.05.001", "4.1.01.001"]
        for r in rows:
            assert r.empresa_id == empresa
            assert r.nome == _NOME_PLACEHOLDER
            assert r.permite_lancamento in (1, True)

    def test_nao_duplica_conta_ja_cadastrada(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "sem_duplicar.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "a4c7f19e2b6d")

        empresa = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        engine = create_engine(url)
        with engine.begin() as conn:
            # Conta já cadastrada manualmente ANTES da migration —
            # nome real, não placeholder.
            conn.execute(text(
                "INSERT INTO contas_contabeis (id, empresa_id, codigo, nome, tipo, "
                "natureza, permite_lancamento, centro_custo_obrigatorio, versao) VALUES "
                "('cc-existente', :empresa, '4.1.01.001', 'Despesas Operacionais', "
                "'despesa', 'debito', 1, 0, 1)"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-2', :empresa, '2026-08-01T00:00:00', 'y', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('s4', 'lanc-2', :empresa, '4.1.01.001', 'debito', 1.00, 'BRL')"
            ), {"empresa": empresa})
        engine.dispose()

        command.upgrade(cfg, "b7e4a2c9f1d3")

        engine = create_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT nome FROM contas_contabeis WHERE empresa_id = :empresa AND codigo = '4.1.01.001'"
            ), {"empresa": empresa}).fetchall()
        engine.dispose()

        # Continua existindo só UMA linha, com o nome real preservado —
        # a migration não sobrescreveu nem duplicou.
        assert len(rows) == 1
        assert rows[0].nome == "Despesas Operacionais"

    def test_sem_dados_em_uso_nao_cria_nada(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "vazio.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "b7e4a2c9f1d3")

        engine = create_engine(url)
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM contas_contabeis")).scalar_one()
        engine.dispose()
        assert total == 0

    def test_downgrade_remove_so_os_placeholders(self, tmp_path, monkeypatch) -> None:
        from alembic import command
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "downgrade.db"
        cfg, url = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "a4c7f19e2b6d")

        empresa = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO contas_contabeis (id, empresa_id, codigo, nome, tipo, "
                "natureza, permite_lancamento, centro_custo_obrigatorio, versao) VALUES "
                "('cc-manual', :empresa, '9.9.99.001', 'Cadastrada manualmente', "
                "'', 'debito', 1, 0, 1)"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO lancamentos (id, empresa_id, criado_em, descricao, "
                "e_parcelado, pre_aprovado, status) VALUES "
                "('lanc-3', :empresa, '2026-08-01T00:00:00', 'z', 0, 0, 'aprovado')"
            ), {"empresa": empresa})
            conn.execute(text(
                "INSERT INTO splits (id, lancamento_id, empresa_id, conta_codigo, "
                "natureza, valor, moeda) VALUES "
                "('s5', 'lanc-3', :empresa, '4.1.01.099', 'debito', 1.00, 'BRL')"
            ), {"empresa": empresa})
        engine.dispose()

        command.upgrade(cfg, "b7e4a2c9f1d3")
        command.downgrade(cfg, "a4c7f19e2b6d")

        engine = create_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT codigo, nome FROM contas_contabeis ORDER BY codigo"
            )).fetchall()
        engine.dispose()

        assert [(r.codigo, r.nome) for r in rows] == [("9.9.99.001", "Cadastrada manualmente")]
