"""Testes de aprovação/rejeição de lançamentos (ADR 008, W3).

Cobre: RBAC via PolicyEngine (não reimplementado na API), segregação de
alçada de valor, justificativa condicional, isolamento por empresa,
transições de status inválidas, auditoria completa.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth.security import hash_senha
from api.main import create_app
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
from core.infra.repositories import LancamentoRepository, UsuarioRepository


@pytest.fixture
def sf(monkeypatch, tmp_path) -> SessionFactory:
    db_path = tmp_path / "test_aprov.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CADERNETA_ENV", "dev")
    factory = SessionFactory(f"sqlite:///{db_path}")
    factory.criar_tabelas()
    return factory


@pytest.fixture
def client(sf: SessionFactory) -> TestClient:
    return TestClient(create_app())


def _usuario(sf: SessionFactory, empresa_id, papel: str, email=None, senha="Senha123!") -> Usuario:
    email = email or f"{papel}@x.com"
    u = Usuario(empresa_id=empresa_id, email=email, nome=papel.title(), papel=papel)
    with sf.session() as session:
        UsuarioRepository(session).criar(u, senha_hash=hash_senha(senha))
    return u


def _lancamento(
    sf: SessionFactory, empresa_id, valor="1000.00", status=StatusLancamento.PENDENTE,
    criado_por="operador", nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
) -> Lancamento:
    """criado_por default = "operador": representa a proveniência real que
    o pipeline grava hoje (Gate 0 — D1). Testes que precisam do cenário de
    origem desconhecida passam criado_por=None explicitamente."""
    lanc = Lancamento(
        empresa_id=empresa_id,
        descricao="Teste aprovação",
        status=status,
        nivel_aprovacao=nivel_aprovacao,
        data_lancamento=date(2026, 6, 1),
        criado_por=criado_por,
        splits=[
            Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                  valor=Dinheiro(Decimal(valor))),
            Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                  valor=Dinheiro(Decimal(valor))),
        ],
    )
    with sf.session() as session:
        LancamentoRepository(session).salvar(lanc)
    return lanc


def _login(client, email, senha="Senha123!"):
    return client.post("/login", json={"email": email, "senha": senha})


class TestAprovarAutenticacao:
    def test_sem_login_retorna_401(self, sf, client) -> None:
        empresa_id = uuid4()
        lanc = _lancamento(sf, empresa_id)
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 401


class TestAprovarRBAC:
    def test_operador_nao_pode_aprovar(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "operador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "operador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 403

    def test_contador_aprova_valor_normal(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, valor="1000.00")

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "aprovado"

    def test_contador_nao_aprova_alto_valor_sem_justificativa(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, valor="6000.00")

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 403  # contador não tem pode_aprovar_alto_valor

    def test_supervisor_aprova_alto_valor_com_justificativa(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "supervisor")
        lanc = _lancamento(sf, empresa_id, valor="6000.00")

        _login(client, "supervisor@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/aprovar",
            json={"justificativa": "Aprovado após revisão contratual"},
        )
        assert r.status_code == 200

    def test_supervisor_alto_valor_sem_justificativa_falha_400(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "supervisor")
        lanc = _lancamento(sf, empresa_id, valor="6000.00")

        _login(client, "supervisor@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 400

    def test_admin_aprova_alto_valor(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "admin")
        lanc = _lancamento(sf, empresa_id, valor="6000.00")

        _login(client, "admin@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/aprovar",
            json={"justificativa": "Aprovado pelo admin"},
        )
        assert r.status_code == 200


class TestAprovarSegregacaoFuncoes:
    """Gate 0 — D1. Cobre o achado registrado: PolicyEngine já tinha a
    regra, mas o único chamador em produção fabricava criador_id="",
    que nunca coincide com um Usuario.id — a segregação nunca disparava.
    """

    def test_origem_desconhecida_bloqueia_aprovacao(self, sf, client) -> None:
        """criado_por=None (falha fechada) — nenhum aprovador é aceito,
        independentemente do papel."""
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, criado_por=None)

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 403
        assert "não pode ser autorizada" in r.json()["detail"] or "identificada" in r.json()["detail"]

    def test_criador_nao_pode_aprovar_proprio_lancamento(self, sf, client) -> None:
        """Cenário que a ausência de criado_por mascarava: o mesmo ator
        que criou o lançamento tenta aprová-lo."""
        empresa_id = uuid4()
        contador = _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, criado_por=str(contador.id))

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 403
        assert "mesmo aprovador" in r.json()["detail"]

    def test_lancamento_de_pipeline_aprovavel_por_qualquer_contador(self, sf, client) -> None:
        """criado_por = proveniência do pipeline (não identidade
        autenticada) — nunca coincide com o UUID de um aprovador humano,
        então a aprovação segue permitida."""
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, criado_por="operador")

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "aprovado"


class TestAprovarCascata:
    """Gate 0 — B3. Reproduzido antes da correção: o router mutava
    status/aprovado_por_1 diretamente, sem chamar Lancamento.aprovar() —
    DOIS_APROVADORES era finalizado com uma única aprovação, e nada
    impedia o mesmo ator de ocupar os dois níveis. Testes aqui passam
    pela rota HTTP real (não só pelo método de domínio isolado), porque
    foi exatamente essa fronteira que produziu o defeito.
    """

    def test_um_aprovador_finaliza_com_uma_aprovacao(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, nivel_aprovacao=NivelAprovacao.UM_APROVADOR)

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "aprovado"

    def test_dois_aprovadores_uma_aprovacao_nao_finaliza(self, sf, client) -> None:
        """O cenário reproduzido no Gate 0: antes da correção, esta
        chamada sozinha resultava em status=aprovado."""
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador", email="x@x.com")
        lanc = _lancamento(sf, empresa_id, nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES)

        _login(client, "x@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 200
        assert r.json()["status"] != "aprovado"
        assert r.json()["status"] == "pendente"

        with sf.session() as session:
            persistido = LancamentoRepository(session).buscar_por_id(lanc.id)
        assert persistido.status == StatusLancamento.PENDENTE
        assert persistido.aprovado_por_1 is not None
        assert persistido.aprovado_por_2 is None

    def test_dois_aprovadores_segundo_aprovador_distinto_finaliza(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador", email="x@x.com")
        _usuario(sf, empresa_id, "supervisor", email="y@x.com")
        lanc = _lancamento(sf, empresa_id, nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES)

        _login(client, "x@x.com")
        r1 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r1.status_code == 200
        assert r1.json()["status"] == "pendente"

        _login(client, "y@x.com")
        r2 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r2.status_code == 200
        assert r2.json()["status"] == "aprovado"

        with sf.session() as session:
            persistido = LancamentoRepository(session).buscar_por_id(lanc.id)
        assert persistido.status == StatusLancamento.APROVADO
        assert persistido.aprovado_por_1 is not None
        assert persistido.aprovado_por_2 is not None
        assert persistido.aprovado_por_1 != persistido.aprovado_por_2

    def test_mesmo_aprovador_nos_dois_niveis_e_negado(self, sf, client) -> None:
        """Gap identificado na revisão: sem esta checagem, corrigir só a
        cascata permitiria o mesmo contador satisfazer os dois níveis
        clicando duas vezes."""
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador", email="x@x.com")
        lanc = _lancamento(sf, empresa_id, nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES)

        _login(client, "x@x.com")
        r1 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r1.status_code == 200
        assert r1.json()["status"] == "pendente"

        r2 = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r2.status_code == 403
        assert "dois níveis" in r2.json()["detail"]

        with sf.session() as session:
            persistido = LancamentoRepository(session).buscar_por_id(lanc.id)
        assert persistido.status == StatusLancamento.PENDENTE
        assert persistido.aprovado_por_2 is None

    def test_rejeicao_apos_aprovacao_parcial(self, sf, client) -> None:
        """O estado intermediário de DOIS_APROVADORES (nível 1 aprovado,
        aguardando nível 2) não deve poder ser convertido por outro
        caminho — rejeição continua disponível e definitiva."""
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador", email="x@x.com")
        _usuario(sf, empresa_id, "supervisor", email="y@x.com")
        lanc = _lancamento(sf, empresa_id, nivel_aprovacao=NivelAprovacao.DOIS_APROVADORES)

        _login(client, "x@x.com")
        client.post(f"/lancamentos/{lanc.id}/aprovar", json={})

        _login(client, "y@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/rejeitar",
            json={"justificativa": "Divergência encontrada após primeira aprovação"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejeitado"

        with sf.session() as session:
            persistido = LancamentoRepository(session).buscar_por_id(lanc.id)
        assert persistido.status == StatusLancamento.REJEITADO


class TestAprovarValidacoes:
    def test_lancamento_inexistente_404(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        _login(client, "contador@x.com")

        r = client.post(f"/lancamentos/{uuid4()}/aprovar", json={})
        assert r.status_code == 404

    def test_lancamento_de_outra_empresa_404(self, sf, client) -> None:
        empresa_a = uuid4()
        empresa_b = uuid4()
        _usuario(sf, empresa_a, "contador")
        lanc_b = _lancamento(sf, empresa_b)

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc_b.id}/aprovar", json={})
        assert r.status_code == 404

    def test_lancamento_ja_aprovado_409(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, status=StatusLancamento.APROVADO)

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        assert r.status_code == 409

    def test_id_malformado_404(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        _login(client, "contador@x.com")

        r = client.post("/lancamentos/nao-e-um-uuid/aprovar", json={})
        assert r.status_code == 404


class TestAprovarAuditoria:
    def test_aprovacao_registra_evento(self, sf, client) -> None:
        from core.infra.unit_of_work import UnitOfWork

        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "contador@x.com")
        client.post(f"/lancamentos/{lanc.id}/aprovar", json={})

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id))
            evt = next(e for e in eventos if e["tipo"] == "LANCAMENTO_APROVADO")
            assert evt["lancamento_id"] == str(lanc.id)
            assert evt["payload"]["papel"] == "contador"

    def test_lancamento_persistido_com_status_aprovado(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "contador@x.com")
        client.post(f"/lancamentos/{lanc.id}/aprovar", json={})

        with sf.session() as session:
            atualizado = LancamentoRepository(session).buscar_por_id(lanc.id)
            assert atualizado.status == StatusLancamento.APROVADO
            assert atualizado.aprovado_por_1 is not None


class TestRejeitar:
    def test_rejeicao_exige_justificativa(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "contador@x.com")
        r = client.post(f"/lancamentos/{lanc.id}/rejeitar", json={})
        assert r.status_code == 400

    def test_rejeicao_com_justificativa_sucesso(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "contador@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/rejeitar",
            json={"justificativa": "Documento fiscal divergente"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejeitado"

    def test_operador_nao_pode_rejeitar(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "operador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "operador@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/rejeitar",
            json={"justificativa": "Tentativa indevida"},
        )
        assert r.status_code == 403

    def test_rejeicao_registra_auditoria_com_justificativa(self, sf, client) -> None:
        from core.infra.unit_of_work import UnitOfWork

        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id)

        _login(client, "contador@x.com")
        client.post(
            f"/lancamentos/{lanc.id}/rejeitar",
            json={"justificativa": "Nota fiscal cancelada"},
        )

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id))
            evt = next(e for e in eventos if e["tipo"] == "LANCAMENTO_REJEITADO")
            assert evt["payload"]["justificativa"] == "Nota fiscal cancelada"

    def test_lancamento_ja_rejeitado_409(self, sf, client) -> None:
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, status=StatusLancamento.REJEITADO)

        _login(client, "contador@x.com")
        r = client.post(
            f"/lancamentos/{lanc.id}/rejeitar",
            json={"justificativa": "Segunda tentativa"},
        )
        assert r.status_code == 409


class TestLimiteConfiguravel:
    def test_limite_customizado_via_env(self, sf, monkeypatch) -> None:
        """LIMITE_APROVACAO_SIMPLES lido a cada requisição, não congelado
        na importação do módulo — confirma o fix aplicado no W3."""
        monkeypatch.setenv("LIMITE_APROVACAO_SIMPLES", "500.00")
        empresa_id = uuid4()
        _usuario(sf, empresa_id, "contador")
        lanc = _lancamento(sf, empresa_id, valor="1000.00")  # acima do limite customizado

        client_limite_baixo = TestClient(create_app())
        _login(client_limite_baixo, "contador@x.com")
        r = client_limite_baixo.post(f"/lancamentos/{lanc.id}/aprovar", json={})
        # contador não tem pode_aprovar_alto_valor — com limite 500, 1000 já é alto valor
        assert r.status_code == 403
