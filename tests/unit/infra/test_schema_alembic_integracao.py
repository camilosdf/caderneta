"""Gate 0 — B2, critérios 7/8/9.

Motivação: os testes unitários da suíte (incluindo os de conciliação em
tests/unit/core/conciliacao/) usam SessionFactory.criar_tabelas(), ou
seja, SQLAlchemy create_all() — não o schema que de fato será implantado
em produção via Alembic (infra/migrations/). O achado do Gate 0 (item
B2) foi justamente essa divergência: usuarios e transacoes_bancarias
existiam nos modelos ORM, a suíte inteira passava, e nenhuma migration
os criava — um deploy real via `alembic upgrade head` não teria essas
tabelas.

Este módulo fecha os três critérios residuais de B2:

B2.8 — guardrail permanente: TestSchemaGuardrail detecta automaticamente
       qualquer novo modelo ORM alterado sem migration correspondente —
       é o teste que teria pego o bug original de B2 antes de chegar ao
       Gate 0, sem depender de alguém lembrar de rodar `alembic upgrade
       head` manualmente.

B2.9 — critérios funcionais (autenticação/RBAC, fluxo de aprovação,
       D1, B3) validados nesta sessão de forma manual/pontual, agora
       reproduzidos aqui como testes permanentes contra schema
       construído exclusivamente por Alembic — não create_all().

B2.7 — fluxo real de conciliação (OFX → TransacaoBancariaRepository →
       MotorConciliacao) exercido contra o mesmo schema migrado,
       reaproveitando os dados de teste já usados no teste hermético
       equivalente (tests/unit/core/conciliacao/test_transacao_repository.py)
       — não duplicados, importados diretamente, para não divergir do
       cenário já coberto ali.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from core.adapters.ofx_bank_statement import OFXBankStatementAdapter
from core.domain.entities import (
    CodigoConta,
    Dinheiro,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    Split,
    StatusLancamento,
    Usuario,
)
from core.infra.db import SessionFactory
from core.infra.repositories import (
    ContaContabilRepository,
    LancamentoRepository,
    TransacaoBancariaRepository,
    UsuarioRepository,
)
from core.rule_engine.motor_conciliacao import MotorConciliacao

from tests.unit.core.conciliacao.test_transacao_repository import OFX_TESTE

ROOT = Path(__file__).parents[3]


def _sessionfactory_via_alembic(db_path: Path, monkeypatch) -> SessionFactory:
    """Constrói um banco exclusivamente via `alembic upgrade head` —
    nunca via create_all(). É o mesmo schema que um deploy real produz.

    infra/migrations/env.py dá precedência à variável de ambiente
    DATABASE_URL sobre a sqlalchemy.url configurada programaticamente
    (para permitir override em produção/CI sem editar alembic.ini). A
    fixture autouse tests/conftest.py::configurar_env_teste já define
    DATABASE_URL apontando para um Postgres de teste — por isso é
    preciso sobrescrevê-la aqui também, e não só `cfg.set_main_option`,
    senão o env.py ignora o SQLite local e tenta conectar ao Postgres
    (bloqueado pelo pytest-socket nesta suíte).

    Também força CADERNETA_ENV=dev, como os demais testes de API
    autenticada (tests/unit/api/test_aprovacao.py etc.) — sem isso,
    SessionMiddleware.https_only fica True (ver api/auth/session.py::
    montar_session_middleware) e o cookie de sessão sai marcado Secure;
    como o TestClient fala http:// (não https://), o cliente httpx
    descarta o cookie silenciosamente e toda requisição autenticada
    subsequente volta 401 — não é uma falha de autenticação real, é o
    mesmo cookie Secure-over-HTTP que o restante da suíte já contorna
    da mesma forma."""
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    # DT-CC-01 / ADR 011, B.2.4 — este é o guardrail deliberado do
    # schema migrado (ver Plano B.2.4, ressalva do usuário): a forma
    # do schema (compare_metadata) não prova enforcement em runtime;
    # enforce_foreign_keys=True torna a FK composta splits ->
    # contas_contabeis e o NOT NULL de empresa_id realmente ativos
    # aqui, ao contrário do resto da suíte hermética (default False —
    # ver SessionFactory.__init__).
    return SessionFactory(url, enforce_foreign_keys=True)


@pytest.fixture
def sf(tmp_path, monkeypatch) -> SessionFactory:
    return _sessionfactory_via_alembic(tmp_path / "alembic_schema.db", monkeypatch)


# =============================================================
# B2.8 — GUARDRAIL PERMANENTE
# =============================================================

class TestSchemaGuardrail:
    def test_schema_alembic_nao_diverge_dos_modelos_orm(self, tmp_path, monkeypatch) -> None:
        """Teria detectado o bug original de B2 automaticamente: se um
        modelo em core/infra/db/models.py for alterado (nova tabela,
        nova coluna, novo índice) sem a migration Alembic correspondente,
        este teste falha listando exatamente a divergência — em vez de
        ficar invisível atrás de create_all() até alguém tentar implantar
        em produção.

        Achado ao rodar junto da suíte completa (não isolado): Base é um
        singleton global de core.infra.db.session, e
        tests/unit/core/test_infra_db.py declara, no nível do módulo, um
        ORM de teste (ModeloTeste/"teste_a1") na MESMA Base para exercitar
        create_all()/drop_all() — uma vez importado por qualquer teste
        anterior no processo, essa tabela fica permanentemente registrada
        em Base.metadata para o resto da sessão do pytest, e este guardrail
        a reportaria como divergência (falso positivo, não regressão real
        de schema). Restringe-se a comparação às tabelas de produção via o
        filtro include_object do Alembic, para que o guardrail continue
        detectando divergências reais independente da ordem de coleta dos
        testes.

        A lista de tabelas de produção é derivada por introspecção de
        core.infra.db.models (toda classe definida NESSE módulo — não
        importada de outro — com __tablename__), não hardcoded: um
        allowlist fixo desatualiza silenciosamente a cada tabela nova
        (ex.: cartoes_credito, faturas_cartao, compras_cartao,
        pagamentos_fatura_cartao não existiam quando este teste foi
        escrito) e o guardrail passaria a ignorar exatamente as tabelas
        mais recentes — o oposto do que ele existe para detectar."""
        import inspect

        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine

        import core.infra.db.models as models_module
        from core.infra.db.session import Base

        tabelas_producao = {
            cls.__tablename__
            for _, cls in inspect.getmembers(models_module, inspect.isclass)
            if cls.__module__ == models_module.__name__ and hasattr(cls, "__tablename__")
        }
        assert tabelas_producao, (
            "Nenhuma tabela de produção encontrada via introspecção de "
            "core.infra.db.models — provável mudança na forma de declarar "
            "os modelos ORM; revisar este teste antes de confiar no "
            "guardrail."
        )

        def _apenas_tabelas_de_producao(object_, name, type_, reflected, compare_to):
            if type_ == "table":
                return name in tabelas_producao
            return True

        db_path = tmp_path / "guardrail.db"
        _sessionfactory_via_alembic(db_path, monkeypatch)

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"include_object": _apenas_tabelas_de_producao}
            )
            diffs = compare_metadata(context, Base.metadata)

        assert diffs == [], (
            "Schema produzido pelas migrations Alembic diverge dos modelos "
            "ORM atuais. Gere uma nova migration "
            "(alembic revision --autogenerate) antes de prosseguir. "
            f"Diferenças encontradas: {diffs!r}"
        )


# =============================================================
# DT-CC-01 / ADR 011, B.2.4 — ENFORCEMENT REAL DA FK COMPOSTA
# =============================================================

class TestEnforcementFKCompostaB24:
    """compare_metadata (TestSchemaGuardrail acima) só prova a FORMA do
    schema — que a FK composta e o NOT NULL existem como constraints.
    Não prova que algo os aplica em runtime (ressalva explícita do
    Plano B.2.4: enforce_foreign_keys=False não pode ser confundido
    com ausência de integridade — o contrato definitivo é o schema
    migrado, demonstrado aqui como realmente ativo)."""

    def test_conta_nao_cadastrada_e_rejeitada(self, sf) -> None:
        from sqlalchemy.exc import IntegrityError

        empresa_id = uuid4()
        lanc = _lancamento(empresa_id)  # conta_codigo nunca cadastrado nesta empresa
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            with sf.session() as session:
                LancamentoRepository(session).salvar(lanc)

    def test_empresa_id_nulo_e_rejeitado(self, sf) -> None:
        from datetime import datetime, timezone

        from sqlalchemy.exc import IntegrityError

        from core.infra.db.models import LancamentoORM, SplitORM

        empresa_id = uuid4()
        _cadastrar_contas_padrao(sf, empresa_id)

        lanc_orm = LancamentoORM(
            id=str(uuid4()), empresa_id=str(empresa_id),
            criado_em=datetime.now(timezone.utc), descricao="teste NOT NULL",
        )
        split_orm = SplitORM(
            id=str(uuid4()), lancamento_id=lanc_orm.id, empresa_id=None,
            conta_codigo="4.1.01.001", natureza="debito", valor=Decimal("10.00"),
            moeda="BRL",
        )
        with pytest.raises(IntegrityError, match="NOT NULL"):
            with sf.session() as session:
                session.add(lanc_orm)
                session.add(split_orm)

    def test_conta_cadastrada_e_aceita(self, sf) -> None:
        empresa_id = uuid4()
        _cadastrar_contas_padrao(sf, empresa_id)
        lanc = _lancamento(empresa_id)

        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        with sf.session() as session:
            persistido = LancamentoRepository(session).buscar_por_id(lanc.id)
            assert persistido is not None
            assert len(persistido.splits) == 2


# =============================================================
# B2.9 — AUTENTICAÇÃO, RBAC E APROVAÇÃO (D1/B3) CONTRA SCHEMA REAL
# =============================================================

class TestFluxosCriticosContraSchemaMigrado:
    """Formaliza como testes permanentes o que foi validado manualmente
    durante o fechamento de D1 e B3 nesta sessão — login, segregação de
    funções e cascata de dois aprovadores, todos contra banco criado só
    por `alembic upgrade head`."""

    def test_autenticacao_e_rbac(self, sf) -> None:
        from api.auth.security import hash_senha

        empresa_id = uuid4()
        with sf.session() as session:
            UsuarioRepository(session).criar(
                Usuario(empresa_id=empresa_id, email="contador@x.com",
                        nome="Contador", papel="contador"),
                senha_hash=hash_senha("Senha123!"),
            )

        client = TestClient(_criar_app(sf))
        r = client.post("/login", json={"email": "contador@x.com", "senha": "Senha123!"})
        assert r.status_code == 200

    def test_segregacao_de_funcoes_d1(self, sf) -> None:
        from api.auth.security import hash_senha

        empresa_id = uuid4()
        with sf.session() as session:
            contador = Usuario(empresa_id=empresa_id, email="x@x.com",
                                nome="X", papel="contador")
            UsuarioRepository(session).criar(contador, senha_hash=hash_senha("Senha123!"))

        _cadastrar_contas_padrao(sf, empresa_id)
        lanc = _lancamento(empresa_id, criado_por=str(contador.id))
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        client = TestClient(_criar_app(sf))
        client.post("/login", json={"email": "x@x.com", "senha": "Senha123!"})
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 403
        assert "mesmo aprovador" in r.json()["detail"]

    def test_cascata_dois_aprovadores_b3(self, sf) -> None:
        from api.auth.security import hash_senha

        empresa_id = uuid4()
        with sf.session() as session:
            repo = UsuarioRepository(session)
            repo.criar(Usuario(empresa_id=empresa_id, email="x@x.com", nome="X", papel="contador"),
                       senha_hash=hash_senha("Senha123!"))
            repo.criar(Usuario(empresa_id=empresa_id, email="y@x.com", nome="Y", papel="supervisor"),
                       senha_hash=hash_senha("Senha123!"))

        _cadastrar_contas_padrao(sf, empresa_id)
        lanc = _lancamento(empresa_id, nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES)
        with sf.session() as session:
            LancamentoRepository(session).salvar(lanc)

        client = TestClient(_criar_app(sf))

        client.post("/login", json={"email": "x@x.com", "senha": "Senha123!"})
        r1 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r1.status_code == 200
        assert r1.json()["status"] == "pendente"

        client.post("/login", json={"email": "y@x.com", "senha": "Senha123!"})
        r2 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r2.status_code == 200
        assert r2.json()["status"] == "aprovado"


# =============================================================
# B2.7 — CONCILIAÇÃO REAL CONTRA SCHEMA MIGRADO
# =============================================================

class TestConciliacaoContraSchemaMigrado:
    def test_idempotencia_e_reforcada_pelo_constraint_do_banco(self, sf) -> None:
        """Verifica que a unicidade (instituicao, numero_conta, fitid) não
        é só uma checagem da aplicação (salvar_se_nova) — o constraint
        criado pela migration (uq_transacao_bancaria_fitid) também
        recusa a duplicata no nível do banco, mesmo contornando o
        repositório."""
        from sqlalchemy.exc import IntegrityError

        from core.infra.db.models import TransacaoBancariaORM

        empresa_id = uuid4()
        orm_1 = TransacaoBancariaORM(
            id=str(uuid4()), empresa_id=str(empresa_id), instituicao="341",
            agencia="0001", numero_conta="12345-6", tipo_conta="corrente",
            fitid="DUP001", data=date(2026, 7, 15), valor="100.00",
            natureza="debito", descricao="teste", referencia="", origem="ofx",
            id_importacao=str(uuid4()), criado_em=date(2026, 7, 15),
        )
        orm_2 = TransacaoBancariaORM(
            id=str(uuid4()), empresa_id=str(empresa_id), instituicao="341",
            agencia="0001", numero_conta="12345-6", tipo_conta="corrente",
            fitid="DUP001", data=date(2026, 7, 16), valor="200.00",
            natureza="debito", descricao="tentativa duplicada", referencia="",
            origem="ofx", id_importacao=str(uuid4()), criado_em=date(2026, 7, 16),
        )
        with sf.session() as session:
            session.add(orm_1)
            session.commit()

        with pytest.raises(IntegrityError):
            with sf.session() as session:
                session.add(orm_2)
                session.commit()

    def test_fluxo_completo_ofx_ate_conciliacao(self, sf, tmp_path) -> None:
        """Mesmo cenário de tests/unit/core/conciliacao/test_transacao_repository.py
        ::TestIntegracaoCompleta.test_fluxo_importar_conciliar, agora
        contra schema construído só por Alembic."""
        empresa_id = uuid4()
        ofx_path = tmp_path / "extrato.ofx"
        ofx_path.write_text(OFX_TESTE, encoding="utf-8")

        adapter = OFXBankStatementAdapter()
        transacoes = adapter.importar(ofx_path, empresa_id, str(uuid4()))
        with sf.session() as session:
            repo = TransacaoBancariaRepository(session)
            for tx in transacoes:
                repo.salvar_se_nova(tx)

        lanc = _lancamento(empresa_id, valor="150.00", data=date(2026, 7, 15))
        lanc.descricao = "SUPERMERCADO ABC"

        with sf.session() as session:
            txs_banco = TransacaoBancariaRepository(session).listar_por_empresa_e_periodo(
                empresa_id, date(2026, 7, 1), date(2026, 7, 31)
            )

        motor = MotorConciliacao()
        relatorio = motor.conciliar(
            lancamentos=[lanc],
            transacoes=txs_banco,
            empresa_id=empresa_id,
            periodo_inicio=date(2026, 7, 1),
            periodo_fim=date(2026, 7, 31),
        )

        assert len(relatorio.conciliados) >= 1
        assert len(relatorio.sem_documento) >= 1


# =============================================================
# HELPERS
# =============================================================

def _cadastrar_contas_padrao(sf: SessionFactory, empresa_id) -> None:
    """DT-CC-01 / ADR 011, B.2.4 — a FK composta splits ->
    contas_contabeis está ativa neste schema (enforce_foreign_keys=True
    nesta fixture, ver _sessionfactory_via_alembic). Os dois códigos
    usados por _lancamento() precisam estar cadastrados antes de
    qualquer persistência via LancamentoRepository, achado durante a
    Fase 3 do Plano B.2.4 (não fazia parte do raio de impacto medido
    na Fase 1 porque, naquele experimento, a FK só existia no modelo
    ORM — nenhuma migration a materializava ainda no schema migrado
    usado por este arquivo)."""
    with sf.session() as session:
        repo = ContaContabilRepository(session)
        repo.criar(empresa_id, "4.1.01.001", "Despesa (teste schema Alembic)",
                   natureza=NaturezaLancamento.DEBITO)
        repo.criar(empresa_id, "1.1.01.002", "Ativo (teste schema Alembic)",
                   natureza=NaturezaLancamento.CREDITO)


def _lancamento(
    empresa_id, valor="1000.00", data=date(2026, 6, 1), criado_por="operador",
    nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
) -> Lancamento:
    return Lancamento(
        empresa_id=empresa_id,
        descricao="Teste schema Alembic",
        status=StatusLancamento.PENDENTE,
        nivel_aprovacao=nivel_aprovacao,
        data_lancamento=data,
        criado_por=criado_por,
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal(valor))),
        ],
    )


def _criar_app(sf: SessionFactory):
    """Cria a app FastAPI apontando para a SessionFactory de teste — os
    testes de aprovação existentes (tests/unit/api/test_aprovacao.py)
    fazem isso via DATABASE_URL + create_app(); aqui a factory já existe
    (construída via Alembic), então sobrescrevemos a dependency
    diretamente para evitar depender de variável de ambiente global."""
    from api.dependencies import get_session_factory
    from api.main import create_app

    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: sf
    return app