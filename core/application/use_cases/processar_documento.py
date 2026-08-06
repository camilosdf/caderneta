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

from core.audit.chain import AuditChain, TipoEvento
from core.events.catalog import (
    DocumentoDuplicado,
    DocumentoErro,
    DocumentoParseado,
    DocumentoRecebido,
    EventBusPort,
    LancamentoCriado,
)
from core.policies.engine import PolicyEngine
from core.ports.classification import ClassificationPort


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
        audit_chain: AuditChain,
        event_bus: EventBusPort,
        exporter,           # ExportadorCSV
        pasta_saida: Path,
    ):
        self._detector = detector
        self._parser_factory = parser_factory
        self._classification = classification_port
        self._policy = policy_engine
        self._audit = audit_chain
        self._bus = event_bus
        self._exporter = exporter
        self._pasta_saida = pasta_saida

    def executar(self, cmd: ComandoProcessarDocumento) -> ResultadoProcessamento:
        from uuid import uuid4
        correlacao = cmd.correlacao_id or str(uuid4())
        resultado = ResultadoProcessamento(sucesso=False, correlacao_id=correlacao)

        try:
            # ── 1. Hash e deduplicação ──────────────────────────────
            hash_doc = self._detector.calcular_hash(cmd.filepath)

            duplicata = self._audit.buscar_por_hash_documento(hash_doc)
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

            # ── 2. Detectar tipo ────────────────────────────────────
            tipo = self._detector.detectar(cmd.filepath)

            self._bus.publicar(DocumentoRecebido(
                correlacao_id=correlacao,
                nome_arquivo=cmd.filepath.name,
                hash_sha256=hash_doc,
                tipo_documento=tipo.value,
                usuario=cmd.usuario,
            ))

            self._audit.registrar(
                tipo=TipoEvento.DOCUMENTO_RECEBIDO,
                payload={"nome_arquivo": cmd.filepath.name, "tipo": tipo.value},
                usuario=cmd.usuario,
                empresa_id=cmd.empresa_id,
                documento_hash=hash_doc,
            )

            # ── 3. Parsear ──────────────────────────────────────────
            parser = self._parser_factory.obter(tipo)
            documentos = list(parser.parsear(cmd.filepath))
            resultado.documentos_processados = len(documentos)

            if not documentos:
                resultado.erros.append("Nenhuma transação encontrada no arquivo.")
                return resultado

            for doc in documentos:
                self._bus.publicar(DocumentoParseado(
                    correlacao_id=correlacao,
                    documento_id=str(doc.id),
                    hash_sha256=hash_doc,
                    fonte_extracao=doc.fonte_extracao.value,
                    confidence_minima=doc.confidence_minima,
                    precisa_revisao=doc.precisa_revisao,
                ))

            # ── 4. Normalizar + Classificar + Gerar lançamentos ─────
            from core.rule_engine.classification_impl import RegrasDeterministicasPlugin
            lancamentos = []

            for doc in documentos:
                norm = self._classification.normalizar_fornecedor(
                    doc.nome_emitente or ""
                )
                sugestao = self._classification.sugerir_categoria(doc, None)
                lancamento = self._construir_lancamento(doc, sugestao, norm, correlacao)

                # Avaliar política de pré-aprovação
                politica = self._policy.avaliar_pre_aprovacao(
                    confidence=lancamento.confidence or 0.0,
                    valor=lancamento.valor_total.valor if lancamento.splits else __import__("decimal").Decimal("0"),
                )
                from core.policies.engine import ResultadoPolitica
                lancamento.pre_aprovado = (
                    politica.resultado == ResultadoPolitica.PERMITIDO
                )

                lancamentos.append(lancamento)

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

                self._audit.registrar(
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
                )

            resultado.lancamentos_criados = len(lancamentos)
            resultado.lancamentos_revisao = sum(1 for l in lancamentos if l.precisa_revisao)

            # ── 5. Exportar CSV ─────────────────────────────────────
            exportacao = self._exporter.exportar(
                lancamentos,
                self._pasta_saida,
                prefixo=cmd.filepath.stem,
                aprovado_por=cmd.usuario,
            )

            self._audit.registrar(
                tipo=TipoEvento.CSV_GERADO,
                payload={
                    "caminho": str(exportacao.caminho),
                    "hash_csv": exportacao.hash_sha256,
                    "total": exportacao.total_lancamentos,
                },
                documento_hash=hash_doc,
                usuario=cmd.usuario,
            )

            # ── 6. Marcar como processado (deduplicação futura) ─────
            self._audit.registrar(
                tipo=TipoEvento.DOCUMENTO_PROCESSADO,
                payload={"nome_arquivo": cmd.filepath.name, "lancamentos": len(lancamentos)},
                documento_hash=hash_doc,
                usuario=cmd.usuario,
            )

            resultado.sucesso = True

        except Exception as e:
            import traceback
            resultado.erros.append(str(e))
            self._bus.publicar(DocumentoErro(
                correlacao_id=correlacao,
                nome_arquivo=cmd.filepath.name,
                hash_sha256="",
                erro=str(e),
                motor="ProcessarDocumentoUseCase",
            ))

        return resultado

    def _construir_lancamento(self, doc, sugestao, norm, correlacao_id):
        """Constrói um Lancamento a partir do documento e da sugestão."""
        from core.domain.entities import (
            Lancamento, Split, NaturezaLancamento, Dinheiro,
            StatusLancamento, NivelAprovacao
        )
        from decimal import Decimal

        valor = doc.valor_liquido or doc.valor_total
        if valor is None:
            valor = Dinheiro(Decimal("0"))

        splits = []
        if sugestao.conta_debito and sugestao.conta_credito:
            splits = [
                Split(
                    conta=sugestao.conta_debito,
                    natureza=NaturezaLancamento.DEBITO,
                    valor=valor,
                ),
                Split(
                    conta=sugestao.conta_credito,
                    natureza=NaturezaLancamento.CREDITO,
                    valor=valor,
                ),
            ]

        l = Lancamento(
            empresa_id=doc.empresa_id if hasattr(doc, "empresa_id") else __import__("uuid").uuid4(),
            documento_id=doc.id,
            data_lancamento=doc.data_emissao,
            descricao=doc.nome_emitente or "SEM DESCRIÇÃO",
            splits=splits,
            categoria=sugestao.categoria,
            confidence=sugestao.confidence,
            metodo_classificacao=sugestao.metodo,
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )

        if splits:
            l.validar()

        return l
