"""Testes do Policy Engine e do catálogo de eventos."""

from decimal import Decimal
from uuid import uuid4

import pytest

from core.domain.entities import Usuario
from core.events.catalog import (
    EventBusEmMemoria,
    LancamentoCriado,
    DocumentoRecebido,
    RegraAlterada,
)
from core.policies.engine import PolicyEngine, ResultadoPolitica


def _usuario(papel: str) -> Usuario:
    return Usuario(email=f"{papel}@x.com", nome=papel.title(), papel=papel)


class TestPolicyEngine:
    @pytest.fixture
    def engine(self):
        return PolicyEngine(limite_aprovacao_simples=Decimal("5000.00"))

    def test_aprovacao_simples_permitida(self, engine):
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("1000.00"),
            aprovador=_usuario("contador"),
            criador_id="operador-uuid",
        )
        assert r.resultado == ResultadoPolitica.PERMITIDO

    def test_papel_sem_permissao_bloqueia(self, engine):
        """Operador não tem pode_aprovar() — bloqueado antes de qualquer
        outra checagem, independentemente de valor ou segregação."""
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("100.00"),
            aprovador=_usuario("operador"),
            criador_id="outro-uuid",
        )
        assert r.resultado == ResultadoPolitica.BLOQUEADO
        assert r.politica_nome == "papel_sem_permissao"

    def test_segregacao_funcoes_bloqueia(self, engine):
        """Criador não pode ser o mesmo que o aprovador."""
        usuario_x = _usuario("contador")
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("100.00"),
            aprovador=usuario_x,
            criador_id=str(usuario_x.id),
        )
        assert r.resultado == ResultadoPolitica.BLOQUEADO
        assert "segregacao" in r.politica_nome

    def test_alto_valor_exige_papel_com_permissao(self, engine):
        """Contador não tem pode_aprovar_alto_valor() — REQUER_ACAO."""
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("6000.00"),
            aprovador=_usuario("contador"),
            criador_id="operador-uuid",
        )
        assert r.resultado == ResultadoPolitica.REQUER_ACAO
        assert r.acao_requerida is not None

    def test_alto_valor_supervisor_permitido(self, engine):
        """Supervisor tem pode_aprovar_alto_valor() — PERMITIDO."""
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("6000.00"),
            aprovador=_usuario("supervisor"),
            criador_id="operador-uuid",
        )
        assert r.resultado == ResultadoPolitica.PERMITIDO

    def test_alto_valor_admin_permitido(self, engine):
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("6000.00"),
            aprovador=_usuario("admin"),
            criador_id="operador-uuid",
        )
        assert r.resultado == ResultadoPolitica.PERMITIDO

    def test_alto_valor_permitido_sinaliza_politica_alto_valor(self, engine):
        """politica_nome permite ao chamador saber que foi alto valor sem
        reimplementar a comparação de limite (ADR 008 — justificativa
        obrigatória em aprovação excepcional)."""
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("6000.00"),
            aprovador=_usuario("supervisor"),
            criador_id="operador-uuid",
        )
        assert r.politica_nome == "aprovacao_alto_valor"

    def test_valor_normal_sinaliza_politica_padrao(self, engine):
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("100.00"),
            aprovador=_usuario("contador"),
            criador_id="operador-uuid",
        )
        assert r.politica_nome == "aprovacao_padrao"

    def test_periodo_fechado_bloqueia(self, engine):
        fechados = {(2026, 5)}
        r = engine.avaliar_periodo(2026, 5, fechados)
        assert r.resultado == ResultadoPolitica.BLOQUEADO

    def test_periodo_aberto_permitido(self, engine):
        fechados = {(2026, 5)}
        r = engine.avaliar_periodo(2026, 6, fechados)
        assert r.resultado == ResultadoPolitica.PERMITIDO

    def test_pre_aprovacao_alta_confianca(self, engine):
        r = engine.avaliar_pre_aprovacao(
            confidence=0.995,
            valor=Decimal("1000.00"),
        )
        assert r.resultado == ResultadoPolitica.PERMITIDO

    def test_pre_aprovacao_confianca_baixa_bloqueada(self, engine):
        r = engine.avaliar_pre_aprovacao(
            confidence=0.85,
            valor=Decimal("500.00"),
        )
        assert r.resultado == ResultadoPolitica.REQUER_ACAO

    def test_pre_aprovacao_alto_valor_bloqueada(self, engine):
        r = engine.avaliar_pre_aprovacao(
            confidence=0.999,
            valor=Decimal("6000.00"),
        )
        assert r.resultado == ResultadoPolitica.REQUER_ACAO

    def test_avaliacao_tem_versao_politica(self, engine):
        r = engine.avaliar_aprovacao(
            valor_lancamento=Decimal("100.00"),
            aprovador=_usuario("contador"),
            criador_id="b",
        )
        assert r.versao_politica >= 1

    def test_avaliacao_tem_id_unico(self, engine):
        r1 = engine.avaliar_aprovacao(Decimal("100"), _usuario("contador"), "b")
        r2 = engine.avaliar_aprovacao(Decimal("100"), _usuario("contador"), "d")
        assert r1.avaliacao_id != r2.avaliacao_id


class TestEventBusEmMemoria:
    def test_publicar_e_escutar(self):
        bus = EventBusEmMemoria()
        recebidos = []
        bus.escutar(LancamentoCriado, lambda e: recebidos.append(e))

        ev = LancamentoCriado(lancamento_id="l1", documento_id="d1", valor="100.00")
        bus.publicar(ev)

        assert len(recebidos) == 1
        assert recebidos[0].lancamento_id == "l1"

    def test_handler_nao_chamado_para_outro_tipo(self):
        bus = EventBusEmMemoria()
        recebidos = []
        bus.escutar(LancamentoCriado, lambda e: recebidos.append(e))

        bus.publicar(DocumentoRecebido(nome_arquivo="a.ofx", hash_sha256="abc", tipo_documento="ofx"))

        assert len(recebidos) == 0

    def test_multiplos_handlers_para_mesmo_evento(self):
        bus = EventBusEmMemoria()
        log1, log2 = [], []
        bus.escutar(RegraAlterada, lambda e: log1.append(e))
        bus.escutar(RegraAlterada, lambda e: log2.append(e))

        bus.publicar(RegraAlterada(regra_id="r1", versao_nova=2, alterado_por="contador"))

        assert len(log1) == 1
        assert len(log2) == 1

    def test_eventos_imutaveis(self):
        ev = LancamentoCriado(lancamento_id="l1")
        with pytest.raises((AttributeError, TypeError)):
            ev.lancamento_id = "outro"  # frozen=True

    def test_limpar_eventos(self):
        bus = EventBusEmMemoria()
        bus.publicar(DocumentoRecebido(nome_arquivo="a.ofx", hash_sha256="x", tipo_documento="ofx"))
        assert len(bus.eventos) == 1
        bus.limpar()
        assert len(bus.eventos) == 0

    def test_correlacao_id_propaga(self):
        bus = EventBusEmMemoria()
        correlacao = str(uuid4())
        ev = LancamentoCriado(correlacao_id=correlacao, lancamento_id="l1")
        bus.publicar(ev)
        assert bus.eventos[0].correlacao_id == correlacao


class TestRegraClassificacaoV2:
    def test_criar_nova_versao_mantem_original(self):
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        regra_v1 = RegraClassificacaoV2(
            nome="Supermercado",
            condicao={"descricao_contains_any": ["MERCADO"]},
            versao=1,
            criada_por="contador",
            reason="Classificar compras em supermercado",
        )
        regra_v2 = regra_v1.criar_nova_versao(
            alterado_por="supervisor",
            motivo_alteracao="Adicionado novo supermercado",
            condicao={"descricao_contains_any": ["MERCADO", "HORTIFRUTI"]},
        )

        assert regra_v1.versao == 1
        assert regra_v2.versao == 2
        assert regra_v2.versao_anterior_id == regra_v1.id
        assert "HORTIFRUTI" in regra_v2.condicao["descricao_contains_any"]
        assert "HORTIFRUTI" not in regra_v1.condicao["descricao_contains_any"]

    def test_desativar_regra_nao_altera_versao(self):
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        regra = RegraClassificacaoV2(nome="Teste", versao=1, criada_por="admin")
        regra.desativar("supervisor", "Regra obsoleta")
        assert regra.ativa is False
        assert regra.versao == 1  # desativar não versiona

    def test_vigencia_temporal(self):
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        from datetime import datetime
        regra = RegraClassificacaoV2(
            nome="Vigente",
            valida_a_partir=datetime(2026, 1, 1),
            valida_ate=datetime(2026, 12, 31),
        )
        assert regra.esta_vigente(datetime(2026, 6, 1)) is True
        assert regra.esta_vigente(datetime(2025, 12, 31)) is False
        assert regra.esta_vigente(datetime(2027, 1, 1)) is False
