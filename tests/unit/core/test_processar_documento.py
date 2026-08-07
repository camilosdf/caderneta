"""Teste de integração — ProcessarDocumentoUseCase com ParserFactory.

Verifica o fluxo completo:
  arquivo → DetectorDocumento → ParserFactory → ClassificationPort
  → PolicyEngine → AuditChain → ExportadorCSV → ResultadoProcessamento

Usa implementações reais onde possível.
Doubles apenas para EventBus (sem efeitos colaterais) e AuditChain (arquivo tmp).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from core.adapters.csv_exporter import ExportadorCSV
from core.application.use_cases.processar_documento import (
    ComandoProcessarDocumento,
    ProcessarDocumentoUseCase,
)
from core.audit.chain import AuditChain
from core.events.catalog import BaseEvento, EventBusEmMemoria
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
def audit(tmp_path: Path) -> AuditChain:
    return AuditChain(tmp_path / "audit.jsonl")


@pytest.fixture
def use_case(tmp_path: Path, pasta_saida: Path, audit: AuditChain) -> ProcessarDocumentoUseCase:
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
        audit_chain=audit,
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
# TESTES — Auditoria
# =============================================================

class TestAuditoria:
    def _ler_eventos(self, audit) -> list[dict]:
        import json
        if not audit._arquivo.exists():
            return []
        with open(audit._arquivo, encoding="utf-8") as f:
            return [json.loads(linha) for linha in f if linha.strip()]

    def test_audit_registra_eventos(self, use_case, csv_nubank, audit):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        assert len(self._ler_eventos(audit)) > 0

    def test_audit_tem_documento_recebido(self, use_case, csv_nubank, audit):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        tipos = [e["tipo"] for e in self._ler_eventos(audit)]
        assert "DOCUMENTO_RECEBIDO" in tipos

    def test_audit_tem_lancamento_gerado(self, use_case, csv_nubank, audit):
        use_case.executar(ComandoProcessarDocumento(
            filepath=csv_nubank,
            usuario="auditado",
            empresa_id="empresa-001",
        ))
        tipos = [e["tipo"] for e in self._ler_eventos(audit)]
        assert "LANCAMENTO_GERADO" in tipos


# =============================================================
# TESTES — Event Bus
# =============================================================

class TestEventBus:
    def test_eventos_publicados(self, tmp_path, pasta_saida):
        from core.domain.entities import CodigoConta
        from core.rule_engine.rule_entity import RegraClassificacaoV2

        bus = EventBusEmMemoria()
        uc = ProcessarDocumentoUseCase(
            detector=DetectorDocumento(),
            parser_factory=ParserFactory(),
            classification_port=RegrasDeterministicasPlugin(regras=[], fornecedores=[]),
            policy_engine=PolicyEngine(),
            audit_chain=AuditChain(tmp_path / "audit.jsonl"),
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
