"""Teste de integração — ProcessarDocumentoUseCase com ParserFactory + UnitOfWork.

Verifica o fluxo completo:
  arquivo → DetectorDocumento → ParserFactory → ClassificationPort
  → PolicyEngine → UnitOfWork/AuditRepository → ExportadorCSV → ResultadoProcessamento

Usa implementações reais onde possível — SQLite em memória para persistência.
Doubles apenas para EventBus (sem efeitos colaterais).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from core.adapters.csv_exporter import ExportadorCSV
from core.application.use_cases.processar_documento import (
    ComandoProcessarDocumento,
    ProcessarDocumentoUseCase,
)
from core.events.catalog import BaseEvento, EventBusEmMemoria
from core.infra.db import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.parsers.detector import DetectorDocumento
from core.pipeline.parser_factory import ParserFactory
from core.policies.engine import PolicyEngine
from core.rule_engine.classification_impl import RegrasDeterministicasPlugin

NF_NS = "http://www.portalfiscal.inf.br/nfe"


# =============================================================
# FIXTURES — arquivos de entrada
# =============================================================

@pytest.fixture
def pasta_saida(tmp_path: Path) -> Path:
    p = tmp_path / "saida"
    p.mkdir()
    return p


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


@pytest.fixture
def use_case(sf: SessionFactory, pasta_saida: Path) -> ProcessarDocumentoUseCase:
    from core.domain.entities import CodigoConta
    from core.rule_engine.rule_entity import RegraClassificacaoV2

    regras = [
        RegraClassificacaoV2(
            nome="Transporte",
            condicao={"descricao_contains_any": ["UBER", "IFOOD"]},
            categoria="Despesas Operacionais",
            conta_debito=CodigoConta("4.1.01.001"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=10,
            criada_por="teste",
        ),
        RegraClassificacaoV2(
            nome="Venda NF-e",
            condicao={"cfop_prefixo": "51"},
            categoria="Receita de Vendas",
            conta_debito=CodigoConta("1.1.01.002"),
            conta_credito=CodigoConta("3.1.01.001"),
            prioridade=5,
            criada_por="teste",
        ),
    ]

    return ProcessarDocumentoUseCase(
        detector=DetectorDocumento(),
        parser_factory=ParserFactory(),
        classification_port=RegrasDeterministicasPlugin(regras=regras, fornecedores=[]),
        policy_engine=PolicyEngine(limite_aprovacao_simples=Decimal("10000.00")),
        session_factory=sf,
        event_bus=EventBusEmMemoria(),
        exporter=ExportadorCSV(),
        pasta_saida=pasta_saida,
    )


@pytest.fixture
def csv_nubank(tmp_path: Path) -> Path:
    f = tmp_path / "nubank.csv"
    f.write_text(
        "date,title,amount\n"
        "2026-06-01,Uber,25.50\n"
        "2026-06-02,iFood,42.90\n",
        encoding="utf-8-sig",
    )
    return f


@pytest.fixture
def nfe_xml(tmp_path: Path) -> Path:
    f = tmp_path / "nfe.xml"
    f.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<nfeProc xmlns="{NF_NS}">'
        f'<NFe><infNFe Id="NFe35240312345678000195550010000000011000000011">'
        f'<ide><nNF>1</nNF><natOp>Venda</natOp><finNFe>1</finNFe>'
        f'<dhEmi>2024-03-15T10:00:00-03:00</dhEmi></ide>'
        f'<emit><CNPJ>12345678000195</CNPJ><xNome>EMPRESA TESTE</xNome></emit>'
        f'<det nItem="1">'
        f'<prod><CFOP>5102</CFOP><NCM>84713012</NCM></prod>'
        f'<imposto><ICMS><ICMS00><CST>00</CST></ICMS00></ICMS></imposto>'
        f'</det>'
        f'<total><ICMSTot>'
        f'<vProd>100.00</vProd><vDesc>0.00</vDesc><vICMS>18.00</vICMS>'
        f'<vIPI>0.00</vIPI><vPIS>1.65</vPIS><vCOFINS>7.60</vCOFINS>'
        f'<vFrete>0.00</vFrete><vNF>100.00</vNF>'
        f'</ICMSTot></total>'
        f'</infNFe></NFe></nfeProc>',
        encoding="utf-8",
    )
    return f


# =============================================================
# TESTES — CSV Nubank
# =============================================================

class TestProcessarCSV:
    def _cmd(self, filepath: Path) -> ComandoProcessarDocumento:
        return ComandoProcessarDocumento(
            filepath=filepath,
            usuario="teste",
            empresa_id="empresa-001",
        )

    def test_sucesso(self, use_case, csv_nubank):
        resultado = use_case.executar(self._cmd(csv_nubank))
        assert resultado.sucesso is True

    def test_documentos_processados(self, use_case, csv_nubank):
        resultado = use_case.executar(self._cmd(csv_nubank))
        assert resultado.documentos_processados == 2

    def test_lancamentos_criados(self, use_case, csv_nubank):
        resultado = use_case.executar(self._cmd(csv_nubank))
        assert resultado.lancamentos_criados == 2

    def test_sem_erros(self, use_case, csv_nubank):
        resultado = use_case.executar(self._cmd(csv_nubank))
        assert resultado.erros == []

    def test_csv_exportado(self, use_case, csv_nubank, pasta_saida):
        use_case.executar(self._cmd(csv_nubank))
        csvs = list(pasta_saida.glob("*.csv"))
        assert len(csvs) == 1

    def test_correlacao_id_presente(self, use_case, csv_nubank):
        resultado = use_case.executar(self._cmd(csv_nubank))
        assert resultado.correlacao_id is not None

    def test_correlacao_id_customizado(self, use_case, csv_nubank):
        cmd = ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="teste",
            empresa_id="empresa-001",
            correlacao_id="corr-123",
        )
        resultado = use_case.executar(cmd)
        assert resultado.correlacao_id == "corr-123"

    def test_deduplicacao_segundo_processamento(self, use_case, csv_nubank):
        use_case.executar(self._cmd(csv_nubank))
        resultado2 = use_case.executar(self._cmd(csv_nubank))
        assert resultado2.sucesso is False
        assert any("já processado" in e for e in resultado2.erros)

    def test_arquivo_inexistente(self, use_case, tmp_path):
        cmd = ComandoProcessarDocumento(
            filepath=tmp_path / "nao_existe.csv",
            usuario="teste",
            empresa_id="empresa-001",
        )
        resultado = use_case.executar(cmd)
        assert resultado.sucesso is False
        assert len(resultado.erros) > 0


# =============================================================
# TESTES — NF-e XML
# =============================================================

class TestProcessarNFe:
    def _cmd(self, filepath: Path) -> ComandoProcessarDocumento:
        return ComandoProcessarDocumento(
            filepath=filepath,
            usuario="teste",
            empresa_id="empresa-001",
        )

    def test_sucesso(self, use_case, nfe_xml):
        resultado = use_case.executar(self._cmd(nfe_xml))
        assert resultado.sucesso is True

    def test_um_documento_processado(self, use_case, nfe_xml):
        resultado = use_case.executar(self._cmd(nfe_xml))
        assert resultado.documentos_processados == 1

    def test_um_lancamento_criado(self, use_case, nfe_xml):
        resultado = use_case.executar(self._cmd(nfe_xml))
        assert resultado.lancamentos_criados == 1

    def test_sem_erros(self, use_case, nfe_xml):
        resultado = use_case.executar(self._cmd(nfe_xml))
        assert resultado.erros == []

    def test_csv_exportado(self, use_case, nfe_xml, pasta_saida):
        use_case.executar(self._cmd(nfe_xml))
        csvs = list(pasta_saida.glob("*.csv"))
        assert len(csvs) == 1

    def test_deduplicacao(self, use_case, nfe_xml):
        use_case.executar(self._cmd(nfe_xml))
        resultado2 = use_case.executar(self._cmd(nfe_xml))
        assert resultado2.sucesso is False


# =============================================================
# TESTES — Auditoria via banco (substituiu JSONL)
# =============================================================

class TestAuditoria:
    def test_audit_registra_eventos(self, use_case, csv_nubank, sf):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa("empresa-001")
            assert len(eventos) > 0

    def test_audit_tem_documento_recebido(self, use_case, csv_nubank, sf):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        with UnitOfWork(sf) as uow:
            tipos = [e["tipo"] for e in uow.audit.listar_por_empresa("empresa-001")]
            assert "DOCUMENTO_RECEBIDO" in tipos

    def test_audit_tem_lancamento_gerado(self, use_case, csv_nubank, sf):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        with UnitOfWork(sf) as uow:
            tipos = [e["tipo"] for e in uow.audit.listar_por_empresa("empresa-001")]
            assert "LANCAMENTO_GERADO" in tipos

    def test_audit_integridade_chain(self, use_case, csv_nubank, sf):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        with UnitOfWork(sf) as uow:
            ok, erros = uow.audit.verificar_integridade()
            assert ok is True
            assert erros == []


# =============================================================
# TESTES — Event Bus
# =============================================================

class TestEventBus:
    def test_eventos_publicados(self, tmp_path, pasta_saida):
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2

        sf = SessionFactory("sqlite:///:memory:")
        sf.criar_tabelas()
        bus = EventBusEmMemoria()
        uc = ProcessarDocumentoUseCase(
            detector=DetectorDocumento(),
            parser_factory=ParserFactory(),
            classification_port=RegrasDeterministicasPlugin(regras=[], fornecedores=[]),
            policy_engine=PolicyEngine(),
            session_factory=sf,
            event_bus=bus,
            exporter=ExportadorCSV(),
            pasta_saida=pasta_saida,
        )

        f = tmp_path / "nubank.csv"
        f.write_text(
            "date,title,amount\n2026-06-01,Uber,25.50\n",
            encoding="utf-8-sig",
        )

        uc.executar(ComandoProcessarDocumento(
            filepath=f, usuario="teste", empresa_id="emp-001"
        ))

        tipos = [type(e).__name__ for e in bus.eventos]
        assert "DocumentoRecebido" in tipos
        assert "LancamentoCriado" in tipos


# =============================================================
# TESTES — LancamentoService integrado (Motor Contábil)
# =============================================================

class TestLancamentoServiceIntegrado:
    def test_periodo_fechado_marca_lancamento_para_revisao(self, sf, pasta_saida, csv_nubank):
        from datetime import date
        from core.domain.entities import CodigoConta, PeriodoContabil, StatusPeriodo
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        from core.rule_engine.lancamento_service import LancamentoService

        regra = RegraClassificacaoV2(
            nome="Transporte",
            condicao={"descricao_contains_any": ["UBER", "IFOOD"]},
            categoria="Despesas Operacionais",
            conta_debito=CodigoConta("4.1.01.001"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=10,
            criada_por="teste",
        )

        periodo_fechado = PeriodoContabil(ano=2026, mes=6, status=StatusPeriodo.FECHADO)
        lancamento_service = LancamentoService(periodo_atual=periodo_fechado)

        uc = ProcessarDocumentoUseCase(
            detector=DetectorDocumento(),
            parser_factory=ParserFactory(),
            classification_port=RegrasDeterministicasPlugin(regras=[regra], fornecedores=[]),
            policy_engine=PolicyEngine(),
            session_factory=sf,
            event_bus=EventBusEmMemoria(),
            exporter=ExportadorCSV(),
            pasta_saida=pasta_saida,
            lancamento_service=lancamento_service,
        )

        resultado = uc.executar(ComandoProcessarDocumento(
            filepath=csv_nubank, usuario="teste", empresa_id="empresa-001",
        ))

        # O processamento continua bem-sucedido — o lançamento é gerado
        # mas marcado para revisão via aviso, não bloqueia o lote inteiro.
        assert resultado.sucesso is True
        assert any("revisão" in a for a in resultado.avisos)

    def test_periodo_aberto_nao_gera_avisos_de_periodo(self, sf, pasta_saida, csv_nubank):
        from core.domain.entities import CodigoConta, PeriodoContabil, StatusPeriodo
        from core.rule_engine.rule_entity import RegraClassificacaoV2
        from core.rule_engine.lancamento_service import LancamentoService

        regra = RegraClassificacaoV2(
            nome="Transporte",
            condicao={"descricao_contains_any": ["UBER", "IFOOD"]},
            categoria="Despesas Operacionais",
            conta_debito=CodigoConta("4.1.01.001"),
            conta_credito=CodigoConta("1.1.01.002"),
            prioridade=10,
            criada_por="teste",
        )

        periodo_aberto = PeriodoContabil(ano=2026, mes=6, status=StatusPeriodo.ABERTO)
        lancamento_service = LancamentoService(periodo_atual=periodo_aberto)

        uc = ProcessarDocumentoUseCase(
            detector=DetectorDocumento(),
            parser_factory=ParserFactory(),
            classification_port=RegrasDeterministicasPlugin(regras=[regra], fornecedores=[]),
            policy_engine=PolicyEngine(),
            session_factory=sf,
            event_bus=EventBusEmMemoria(),
            exporter=ExportadorCSV(),
            pasta_saida=pasta_saida,
            lancamento_service=lancamento_service,
        )

        resultado = uc.executar(ComandoProcessarDocumento(
            filepath=csv_nubank, usuario="teste", empresa_id="empresa-001",
        ))

        assert resultado.sucesso is True
        assert not any("revisão" in a for a in resultado.avisos)

    def test_sem_lancamento_service_usa_default(self, sf, pasta_saida, csv_nubank):
        """Sem injetar lancamento_service, o use case usa LancamentoService() padrão
        (sem validação de período/contas) — comportamento retrocompatível."""
        uc = ProcessarDocumentoUseCase(
            detector=DetectorDocumento(),
            parser_factory=ParserFactory(),
            classification_port=RegrasDeterministicasPlugin(regras=[], fornecedores=[]),
            policy_engine=PolicyEngine(),
            session_factory=sf,
            event_bus=EventBusEmMemoria(),
            exporter=ExportadorCSV(),
            pasta_saida=pasta_saida,
        )
        resultado = uc.executar(ComandoProcessarDocumento(
            filepath=csv_nubank, usuario="teste", empresa_id="empresa-001",
        ))
        assert resultado.sucesso is True
