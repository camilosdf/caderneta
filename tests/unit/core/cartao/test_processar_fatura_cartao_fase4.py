"""Testes de Fase 4 — Idempotência (D13) e Eventos — ProcessarFaturaCartao.

Cobre: persistência idempotente via FaturaCartaoRepository, publicação
de FaturaCartaoRecebida/FaturaCartaoFechada no EventBusPort, registro
correspondente em TipoEvento (hash chain), e preservação exata do
comportamento da Fase 2 quando session_factory/event_bus não são
injetados (regressão).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from core.application.use_cases.processar_fatura_cartao import (
    ProcessarFaturaCartaoUseCase,
)
from core.audit.chain import TipoEvento
from core.domain.entities import StatusFechamentoFatura, TipoDocumento
from core.events.catalog import EventBusEmMemoria, FaturaCartaoFechada, FaturaCartaoRecebida
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

_TEXTO_FATURA_FECHADA = """\
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
06/08 IFOOD DELIVERY R$ 48,50
Total desta fatura R$ 74,40
"""

_TEXTO_FATURA_DIVERGENTE = """\
Vencimento: 15/09/2026
05/08 UBER TRIP R$ 25,90
Total desta fatura R$ 999,00
"""


def _detector_mock(tipo: TipoDocumento = TipoDocumento.PDF_TEXTO, hash_doc: str = "hash-fixo") -> MagicMock:
    mock = MagicMock()
    mock.detectar.return_value = tipo
    mock.calcular_hash.return_value = hash_doc
    return mock


def _pdfplumber_mock(texto: str):
    pagina = MagicMock()
    pagina.extract_text.return_value = texto
    pdf_mock = MagicMock()
    pdf_mock.__enter__.return_value.pages = [pagina]
    pdf_mock.__exit__.return_value = False
    return pdf_mock


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


# =============================================================
# PERSISTÊNCIA IDEMPOTENTE — D13
# =============================================================

class TestPersistenciaIdempotente:
    def test_fatura_nova_e_persistida(self):
        sf = _session_factory()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf)
        empresa_id, cartao_id = uuid4(), uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)

        assert resultado.duplicada is False
        with UnitOfWork(sf) as uow:
            persistida = uow.faturas_cartao.buscar_por_id(resultado.fatura.id)
        assert persistida is not None
        assert len(persistida.itens) == 2

    def test_reprocessar_mesma_fatura_nao_duplica(self):
        """D13 — mesmo cartão + mesmo período (mesmo hash de arquivo,
        segundo processamento) não gera segunda linha."""
        sf = _session_factory()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf)
        empresa_id, cartao_id = uuid4(), uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            r1 = uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)
            r2 = uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)

        assert r1.duplicada is False
        assert r2.duplicada is True
        assert any("idempotência" in a.lower() or "já processada" in a.lower() for a in r2.avisos)

        with UnitOfWork(sf) as uow:
            faturas = uow.faturas_cartao.listar_por_empresa(empresa_id)
        assert len(faturas) == 1  # nunca duas

    def test_documento_e_salvo_mesmo_quando_fatura_e_duplicada(self):
        """O registro do Documento (arquivo bruto) não é bloqueado pela
        idempotência de FaturaCartao — são chaves de níveis diferentes (D13)."""
        sf = _session_factory()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf)
        empresa_id, cartao_id = uuid4(), uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)
            r2 = uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)

        with UnitOfWork(sf) as uow:
            doc = uow.documentos.buscar_por_id(r2.documento.id)
        assert doc is not None


# =============================================================
# EVENTOS — BaseEvento (EventBusPort)
# =============================================================

class TestEventosBarramento:
    def test_fatura_fechada_publica_recebida_e_fechada(self):
        sf = _session_factory()
        bus = EventBusEmMemoria()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf, event_bus=bus)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4(), cartao_id=uuid4())

        tipos_publicados = [type(e) for e in bus.eventos]
        assert FaturaCartaoRecebida in tipos_publicados
        assert FaturaCartaoFechada in tipos_publicados
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.FECHADA

    def test_fatura_divergente_publica_so_recebida(self):
        """D5 — fatura DIVERGENTE não é 'fechada', logo não publica
        FaturaCartaoFechada."""
        sf = _session_factory()
        bus = EventBusEmMemoria()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf, event_bus=bus)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_DIVERGENTE)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4(), cartao_id=uuid4())

        tipos_publicados = [type(e) for e in bus.eventos]
        assert FaturaCartaoRecebida in tipos_publicados
        assert FaturaCartaoFechada not in tipos_publicados
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.DIVERGENTE

    def test_fatura_duplicada_nao_republica_eventos(self):
        """Reprocessar uma fatura já persistida não deve gerar novos
        eventos — idempotência também vale para o barramento."""
        sf = _session_factory()
        bus = EventBusEmMemoria()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf, event_bus=bus)
        empresa_id, cartao_id = uuid4(), uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)
            n_eventos_apos_primeira = len(bus.eventos)
            uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=cartao_id)

        assert len(bus.eventos) == n_eventos_apos_primeira  # nenhum evento novo


# =============================================================
# EVENTOS — TipoEvento (hash chain / auditoria persistida)
# =============================================================

class TestEventosAuditoria:
    def test_evento_fatura_recebida_registrado_na_chain(self):
        sf = _session_factory()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf)
        empresa_id = uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=uuid4())

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id))

        tipos = {e["tipo"] for e in eventos}
        assert TipoEvento.FATURA_CARTAO_RECEBIDA.value in tipos
        assert TipoEvento.FATURA_CARTAO_FECHADA.value in tipos

    def test_fatura_divergente_nao_registra_evento_fechada_na_chain(self):
        sf = _session_factory()
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector, session_factory=sf)
        empresa_id = uuid4()

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_DIVERGENTE)):
            uc.executar(Path("fatura.pdf"), empresa_id=empresa_id, cartao_id=uuid4())

        with UnitOfWork(sf) as uow:
            eventos = uow.audit.listar_por_empresa(str(empresa_id))

        tipos = {e["tipo"] for e in eventos}
        assert TipoEvento.FATURA_CARTAO_RECEBIDA.value in tipos
        assert TipoEvento.FATURA_CARTAO_FECHADA.value not in tipos


# =============================================================
# REGRESSÃO — Fase 2 sem session_factory/event_bus
# =============================================================

class TestRegressaoSemPersistencia:
    def test_comportamento_identico_a_fase_2_sem_dependencias_injetadas(self):
        """Sem session_factory nem event_bus, nada é persistido nem
        publicado — mesmo comportamento em memória da Fase 2."""
        detector = _detector_mock()
        uc = ProcessarFaturaCartaoUseCase(detector=detector)

        with patch("pdfplumber.open", return_value=_pdfplumber_mock(_TEXTO_FATURA_FECHADA)):
            resultado = uc.executar(Path("fatura.pdf"), empresa_id=uuid4())

        assert resultado.duplicada is False
        assert resultado.fatura.status_fechamento == StatusFechamentoFatura.FECHADA
        assert len(resultado.fatura.itens) == 2
