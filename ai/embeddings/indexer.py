"""EmbeddingsIndexer — Etapa 7.3.

Constrói um EmbeddingsPlugin pronto para uso a partir do histórico
de lançamentos aprovados em banco.

Separação de responsabilidades:
  HistoricoRepository  → sabe buscar candidatos no banco
  EmbeddingsPlugin     → sabe classificar por similaridade
  EmbeddingsIndexer    → orquestra os dois, mantém o índice atualizado

O índice vive em memória (MVP). pgvector para persistência de embeddings
é a evolução natural quando o histórico crescer além de ~1000 lançamentos.
"""

import logging
from typing import Optional
from uuid import UUID

from ai.embeddings.embeddings_plugin import EmbeddingsPlugin
from ai.embeddings.historico_repository import HistoricoRepository
from core.infra.db.session import SessionFactory
from core.ports.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingsIndexer:
    """Mantém um EmbeddingsPlugin atualizado com o histórico do banco.

    Uso típico no startup da API:
        indexer = EmbeddingsIndexer(session_factory, provider, empresa_id)
        plugin = indexer.construir()
        orchestrator = ClassifierOrchestrator(regras=regras, embeddings=plugin)

    O índice é reconstruído sob demanda (refresh()) — não há atualização
    automática em tempo real. Para o MVP, reconstruir ao iniciar a aplicação
    é suficiente. Cache e atualização incremental são melhorias futuras.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        provider: EmbeddingProvider,
        empresa_id: UUID,
        limit: int = 500,
        threshold_classificar: float = 0.85,
        threshold_revisao: float = 0.70,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._empresa_id = empresa_id
        self._limit = limit
        self._threshold_classificar = threshold_classificar
        self._threshold_revisao = threshold_revisao
        self._plugin: Optional[EmbeddingsPlugin] = None

    def construir(self) -> EmbeddingsPlugin:
        """Constrói ou reconstrói o índice a partir do histórico atual.

        Sempre executa uma nova consulta ao banco — sem cache de sessão anterior.
        """
        with self._session_factory.session() as session:
            repo = HistoricoRepository(session)
            candidatos = repo.obter_candidatos(
                empresa_id=self._empresa_id,
                limit=self._limit,
            )

        if not candidatos:
            logger.info(
                "EmbeddingsIndexer: histórico vazio para empresa %s — "
                "EmbeddingsPlugin sem candidatos (modo revisão obrigatória).",
                self._empresa_id,
            )
            self._plugin = EmbeddingsPlugin(
                provider=self._provider,
                candidatos=[],
                threshold_classificar=self._threshold_classificar,
                threshold_revisao=self._threshold_revisao,
            )
            return self._plugin

        logger.info(
            "EmbeddingsIndexer: indexando %d candidatos para empresa %s...",
            len(candidatos),
            self._empresa_id,
        )

        # Calcular embeddings em batch (mais eficiente que um a um)
        textos = [c.descricao for c in candidatos]
        embeddings = self._provider.encode_batch(textos)
        for candidato, emb in zip(candidatos, embeddings):
            candidato.embedding = emb

        self._plugin = EmbeddingsPlugin(
            provider=self._provider,
            candidatos=candidatos,
            threshold_classificar=self._threshold_classificar,
            threshold_revisao=self._threshold_revisao,
        )

        logger.info("EmbeddingsIndexer: índice construído com sucesso.")
        return self._plugin

    def refresh(self) -> EmbeddingsPlugin:
        """Reconstrói o índice — alias semântico de construir()."""
        return self.construir()

    @property
    def plugin(self) -> Optional[EmbeddingsPlugin]:
        """Plugin atual, ou None se construir() ainda não foi chamado."""
        return self._plugin

    @property
    def total_candidatos(self) -> int:
        """Quantidade de candidatos no índice atual."""
        if self._plugin is None:
            return 0
        return len(self._plugin._candidatos)
