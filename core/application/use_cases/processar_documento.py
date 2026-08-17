"""Use case: ProcessarDocumento — camada de aplicação (ADR 006).

O pipeline não conhece regras de negócio.
Este use case orquestra via eventos — cada etapa publica e o pipeline
avança reagindo ao que aconteceu, não chamando diretamente o próximo motor.

Fluxo:
  DocumentoRecebido → validação → parsing → normalização →
  classificação → LancamentoCriado → fila de aprovação
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.audit.chain import TipoEvento
from core.events.catalog import (
    DocumentoDuplicado,
    DocumentoErro,
    DocumentoParseado,
    DocumentoRecebido,
    EventBusPort,
    LancamentoCriado,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork
from core.policies.engine import PolicyEngine
from core.ports.classification import ClassificationPort
from core.rule_engine.lancamento_service import (
    CentroCustoObrigatorioError,
    ContaNaoLancavelError,
    LancamentoService,
    PeriodoFechadoError,
)
from shared.identifiers import empresa_id_from_string


@dataclass
class ComandoProcessarDocumento:
    """Dados de entrada para o use case."""
    filepath: Path
    usuario: str
    empresa_id: str
    correlacao_id: Optional[str] = None


@dataclass
class ResultadoProcessamento:
    """Resultado do use case."""
    sucesso: bool
    correlacao_id: str
    documentos_processados: int = 0
    lancamentos_criados: int = 0
    lancamentos_revisao: int = 0
    erros: list[str] = None
    avisos: list[str] = None

    def __post_init__(self):
        if self.erros is None:
            self.erros = []
        if self.avisos is None:
            self.avisos = []


class ProcessarDocumentoUseCase:
    """
    Orquestra o processamento de um documento financeiro.

    Dependências injetadas via construtor — nenhuma importação direta
    de implementações concretas. Apenas Ports (Protocols).
    """

    def __init__(
        self,
        detector,           # DetectorDocumento
        parser_factory,     # factory que retorna o parser correto por tipo
        classification_port: ClassificationPort,
        policy_engine: PolicyEngine,
        session_factory: SessionFactory,
        event_bus: EventBusPort,
        exporter,           # ExportadorCSV
        pasta_saida: Path,
        lancamento_service: Optional[LancamentoService] = None,
    ):
        self._detector = detector
        self._parser_factory = parser_factory
        self._classification = classification_port
        self._policy = policy_engine
        self._session_factory = session_factory
        self._bus = event_bus
        self._exporter = exporter
        self._pasta_saida = pasta_saida
        self._lancamento_service = lancamento_service or LancamentoService()

    def executar(self, cmd: ComandoProcessarDocumento) -> ResultadoProcessamento:
        from uuid import uuid4
        correlacao = cmd.correlacao_id or str(uuid4())
        resultado = ResultadoProcessamento(sucesso=False, correlacao_id=correlacao)

        try:
            with UnitOfWork(self._session_factory) as uow:
                # ── 1. Hash e deduplicação ──────────────────────────
                hash_doc = self._detector.calcular_hash(cmd.filepath)

                duplicata = uow.audit.buscar_por_documento(hash_doc, empresa_id=cmd.empresa_id)
                if duplicata:
                    self._bus.publicar(DocumentoDuplicado(
                        correlacao_id=correlacao,
                        hash_sha256=hash_doc,
                        primeiro_processamento=duplicata.get("timestamp", ""),
                    ))
                    resultado.erros.append(
                        f"Documento já processado em {duplicata.get('timestamp', '?')}."
                    )
                    return resultado

                # ── 2. Detectar tipo ─────────────────────────────────
                tipo = self._detector.detectar(cmd.filepath)

                self._bus.publicar(DocumentoRecebido(
                    correlacao_id=correlacao,
                    nome_arquivo=cmd.filepath.name,
                    hash_sha256=hash_doc,
                    tipo_documento=tipo.value,
                    usuario=cmd.usuario,
                ))

                uow.audit.registrar(
                    tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                    payload={"nome_arquivo": cmd.filepath.name, "tipo": tipo.value},
                    usuario=cmd.usuario,
                    empresa_id=cmd.empresa_id,
                    documento_hash=hash_doc,
                )

                # ── 3. Parsear ───────────────────────────────────────
                parser = self._parser_factory.obter(tipo)
                documentos = list(parser.parsear(cmd.filepath))
                resultado.documentos_processados = len(documentos)

                if not documentos:
                    resultado.erros.append("Nenhuma transação encontrada no arquivo.")
                    return resultado

                # Parsers não conhecem o contexto de negócio (empresa) — o
                # use case é quem sabe a qual empresa este processamento
                # pertence. Sobrescreve o empresa_id aleatório do parser
                # pelo identificador real do comando, para que Documento,
                # Lancamento e PeriodoContabil fiquem consistentes.
                empresa_id = empresa_id_from_string(cmd.empresa_id)
                for doc in documentos:
                    doc.empresa_id = empresa_id
                    uow.documentos.salvar(doc)

                for doc in documentos:
                    self._bus.publicar(DocumentoParseado(
                        correlacao_id=correlacao,
                        documento_id=str(doc.id),
                        hash_sha256=hash_doc,
                        fonte_extracao=doc.fonte_extracao.value,
                        confidence_minima=doc.confidence_minima,
                        precisa_revisao=doc.precisa_revisao,
                    ))

                # ── 4. Normalizar + Classificar + Gerar lançamentos ──
                lancamentos = []

                for doc in documentos:
                    norm = self._classification.normalizar_fornecedor(
                        doc.nome_emitente or ""
                    )
                    sugestao = self._classification.sugerir_categoria(doc, None)

                    try:
                        lancamento = self._lancamento_service.processar(doc, sugestao)
                    except (ValueError, ContaNaoLancavelError, CentroCustoObrigatorioError, PeriodoFechadoError) as e:
                        # Falha de validação contábil (período fechado, conta
                        # não lançável, centro de custo ausente): o lançamento
                        # é construído sem validação e fica marcado para revisão.
                        lancamento = self._lancamento_service.construir(doc, sugestao)
                        resultado.avisos.append(
                            f"Lançamento de '{doc.nome_emitente}' requer revisão: {e}"
                        )

                    # Gate 0 — D1: autoria do lançamento. cmd.usuario é
                    # proveniência operacional (texto livre de --usuario na
                    # CLI, sem validação contra a tabela usuarios) — não é
                    # identidade autenticada. Suficiente para que a fila de
                    # aprovação (Interface Web) nunca veja criado_por vazio,
                    # e para auditoria de origem; não deve ser tratado como
                    # prova de identidade humana forte.
                    lancamento.criado_por = cmd.usuario

                    politica = self._policy.avaliar_pre_aprovacao(
                        confidence=lancamento.confidence or 0.0,
                        valor=lancamento.valor_total.valor,
                    )
                    from core.policies.engine import ResultadoPolitica
                    lancamento.pre_aprovado = (
                        bool(lancamento.splits)
                        and politica.resultado == ResultadoPolitica.PERMITIDO
                    )

                    lancamentos.append(lancamento)
                    uow.lancamentos.salvar(lancamento)

                    self._bus.publicar(LancamentoCriado(
                        correlacao_id=correlacao,
                        lancamento_id=str(lancamento.id),
                        documento_id=str(doc.id),
                        valor=str(lancamento.valor_total.valor) if lancamento.splits else "0",
                        conta_debito=lancamento.splits[0].conta.codigo if lancamento.splits else "",
                        conta_credito=lancamento.splits[-1].conta.codigo if lancamento.splits else "",
                        nivel_aprovacao=lancamento.nivel_aprovacao.value if lancamento.nivel_aprovacao else "",
                        pre_aprovado=lancamento.pre_aprovado,
                    ))

                    uow.audit.registrar(
                        tipo=TipoEvento.LANCAMENTO_GERADO,
                        payload={
                            "valor": str(lancamento.valor_total.valor) if lancamento.splits else "0",
                            "pre_aprovado": lancamento.pre_aprovado,
                            "confidence": lancamento.confidence,
                        },
                        lancamento_id=str(lancamento.id),
                        documento_id=str(doc.id),
                        documento_hash=hash_doc,
                        usuario=cmd.usuario,
                        empresa_id=cmd.empresa_id,
                    )

                resultado.lancamentos_criados = len(lancamentos)
                resultado.lancamentos_revisao = sum(1 for l in lancamentos if l.precisa_revisao)

                # ── 5. Exportar CSV ──────────────────────────────────
                exportacao = self._exporter.exportar(
                    lancamentos,
                    self._pasta_saida,
                    prefixo=cmd.filepath.stem,
                    aprovado_por=cmd.usuario,
                )

                # Marca os lançamentos como exportados — habilita o comando
                # `caderneta lancamentos listar --status exportado` e o
                # fluxo de conciliação manual com o GnuCash.
                from core.domain.entities import StatusLancamento
                from datetime import datetime, timezone

                agora = datetime.now(timezone.utc)
                for lancamento in lancamentos:
                    lancamento.status = StatusLancamento.EXPORTADO
                    lancamento.exportado_em = agora
                    uow.lancamentos.salvar(lancamento)

                uow.audit.registrar(
                    tipo=TipoEvento.CSV_GERADO,
                    payload={
                        "caminho": str(exportacao.caminho),
                        "hash_csv": exportacao.hash_sha256,
                        "total": exportacao.total_lancamentos,
                    },
                    documento_hash=hash_doc,
                    usuario=cmd.usuario,
                    empresa_id=cmd.empresa_id,
                )

                # ── 6. Marcar como processado (deduplicação futura) ──
                uow.audit.registrar(
                    tipo=TipoEvento.DOCUMENTO_PROCESSADO,
                    payload={"nome_arquivo": cmd.filepath.name, "lancamentos": len(lancamentos)},
                    documento_hash=hash_doc,
                    usuario=cmd.usuario,
                    empresa_id=cmd.empresa_id,
                )

                uow.commit()
                resultado.sucesso = True

        except Exception as e:
            resultado.erros.append(str(e))
            self._bus.publicar(DocumentoErro(
                correlacao_id=correlacao,
                nome_arquivo=cmd.filepath.name,
                hash_sha256="",
                erro=str(e),
                motor="ProcessarDocumentoUseCase",
            ))

        return resultado
