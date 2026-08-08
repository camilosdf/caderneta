"""EmbeddingsPlugin — Etapa 7.1/7.2/7.3.

Implementa ClassificationPort via busca semântica no histórico de
lançamentos aprovados. Nunca decide sozinho: retorna Sugestao com
precisa_revisao=True quando confiança está abaixo do threshold, ou
quando o histórico está vazio.

IMPORTANTE — princípio arquitetural (do parecer de Etapa 7):
  O EmbeddingsPlugin NÃO incorpora as regras determinísticas.
  A composição (regras → embeddings → fallback) é responsabilidade
  do ClassifierOrchestrator, não deste plugin.

  ✓ ClassifierOrchestrator → chama RegrasDeterministicasPlugin
                            → se não cobriu, chama EmbeddingsPlugin
  ✗ EmbeddingsPlugin → chama RegrasDeterministicasPlugin internamente

Isso preserva o princípio de responsabilidade única e evita que uma
decisão de precedência fique escondida dentro de um plugin de IA.
"""

from dataclasses import dataclass, field

from core.domain.entities import CodigoConta, Documento, Fornecedor
from core.ports.classification import ResultadoNormalizacao, Sugestao
from core.ports.embedding import EmbeddingProvider


@dataclass
class CandidatoHistorico:
    """Um lançamento aprovado que serve como referência de classificação."""
    descricao: str
    categoria: str
    conta_debito: str
    conta_credito: str
    centro_custo: str | None = None
    embedding: list[float] = field(default_factory=list)


class EmbeddingsPlugin:
    """Classificação por similaridade semântica no histórico de lançamentos.

    Satisfaz ClassificationPort via duck typing (Protocol estrutural).
    Não herda de nenhuma classe base — mesma disciplina de
    RegrasDeterministicasPlugin.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        candidatos: list[CandidatoHistorico] | None = None,
        threshold_classificar: float = 0.85,
        threshold_revisao: float = 0.70,
        conta_fallback_debito: str = "4.1.01.099",
        conta_fallback_credito: str = "1.1.01.002",
    ) -> None:
        """
        Args:
            provider: EmbeddingProvider a usar (SentenceTransformerProvider em
                      produção, FakeEmbeddingProvider em testes).
            candidatos: histórico de lançamentos aprovados com embeddings
                        pré-computados. None ou lista vazia → sem histórico
                        → sempre precisa_revisao=True.
            threshold_classificar: similaridade mínima para aceitar como
                        classificação com confidence alta (precisa_revisao=False).
            threshold_revisao: similaridade mínima para sugerir algo (com
                        precisa_revisao=True). Abaixo disso → fallback vazio.
        """
        self._provider = provider
        self._candidatos = candidatos or []
        self._threshold_classificar = threshold_classificar
        self._threshold_revisao = threshold_revisao
        self._conta_fallback_debito = CodigoConta(conta_fallback_debito)
        self._conta_fallback_credito = CodigoConta(conta_fallback_credito)

    # ── ClassificationPort ────────────────────────────────────────────────

    def sugerir_categoria(
        self,
        documento: Documento,
        fornecedor: Fornecedor | None,
    ) -> Sugestao:
        """Sugere categoria via similaridade semântica no histórico.

        Retorna precisa_revisao=True quando:
        - histórico vazio;
        - melhor similarity < threshold_revisao;
        - threshold_revisao ≤ similarity < threshold_classificar.

        Nunca inventa uma categoria com alta confiança na ausência de
        histórico suficiente — encaminha para revisão humana.
        """
        if not self._candidatos:
            return self._sem_historico(documento)

        texto_consulta = _texto_documento(documento)
        vetor_consulta = self._provider.encode(texto_consulta)

        melhor_sim, melhor = self._buscar_melhor(vetor_consulta)

        if melhor is None or melhor_sim < self._threshold_revisao:
            return self._sem_historico(documento)

        precisa_revisao = melhor_sim < self._threshold_classificar
        confidence = _sim_para_confidence(melhor_sim)

        return Sugestao(
            categoria=melhor.categoria,
            conta_debito=CodigoConta(melhor.conta_debito),
            conta_credito=CodigoConta(melhor.conta_credito),
            centro_custo=melhor.centro_custo,
            confidence=confidence,
            metodo="embedding",
            precisa_revisao=precisa_revisao,
            motivo=(
                f"Similaridade {melhor_sim:.2%} com '{melhor.descricao[:50]}'"
                + (" — revisão recomendada" if precisa_revisao else "")
            ),
        )

    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao:
        """Normalização semântica de fornecedor por embedding.

        Busca no histórico de candidatos o mais similar ao nome bruto.
        Sem histórico → retorna como novo fornecedor.
        """
        if not self._candidatos:
            return ResultadoNormalizacao(
                fornecedor_id=None,
                nome_canonico=nome_raw,
                confidence=0.0,
                metodo="embedding",
                precisa_revisao=True,
            )

        vetor = self._provider.encode(nome_raw)
        melhor_sim, melhor = self._buscar_melhor(vetor)

        if melhor is None or melhor_sim < self._threshold_revisao:
            return ResultadoNormalizacao(
                fornecedor_id=None,
                nome_canonico=nome_raw,
                confidence=0.0,
                metodo="embedding",
                precisa_revisao=True,
            )

        return ResultadoNormalizacao(
            fornecedor_id=None,  # preenchido pelo caller com dados do banco
            nome_canonico=melhor.descricao,
            confidence=_sim_para_confidence(melhor_sim),
            metodo="embedding",
            precisa_revisao=melhor_sim < self._threshold_classificar,
        )

    # ── Utilitários de indexação ──────────────────────────────────────────

    @classmethod
    def de_lancamentos(
        cls,
        provider: EmbeddingProvider,
        lancamentos: list[dict],
        **kwargs,
    ) -> "EmbeddingsPlugin":
        """Factory: cria o plugin a partir de uma lista de lançamentos aprovados.

        Cada lançamento deve ter as chaves:
            descricao, categoria, conta_debito, conta_credito
        Opcional: centro_custo.

        Os embeddings são computados em batch (eficiência).
        """
        candidatos = []
        textos = []

        for lanc in lancamentos:
            descricao = lanc.get("descricao", "")
            textos.append(descricao)
            candidatos.append(CandidatoHistorico(
                descricao=descricao,
                categoria=lanc.get("categoria", ""),
                conta_debito=lanc.get("conta_debito", "4.1.01.099"),
                conta_credito=lanc.get("conta_credito", "1.1.01.002"),
                centro_custo=lanc.get("centro_custo"),
            ))

        if textos:
            embeddings = provider.encode_batch(textos)
            for candidato, emb in zip(candidatos, embeddings, strict=False):
                candidato.embedding = emb

        return cls(provider=provider, candidatos=candidatos, **kwargs)

    # ── Internos ──────────────────────────────────────────────────────────

    def _buscar_melhor(
        self,
        vetor_consulta: list[float],
    ) -> tuple[float, CandidatoHistorico | None]:
        """Retorna (similaridade, candidato) do resultado mais similar."""
        melhor_sim = -1.0
        melhor: CandidatoHistorico | None = None

        for candidato in self._candidatos:
            if not candidato.embedding:
                continue
            sim = _produto_interno(vetor_consulta, candidato.embedding)
            if sim > melhor_sim:
                melhor_sim = sim
                melhor = candidato

        return melhor_sim, melhor

    def _sem_historico(self, documento: Documento) -> Sugestao:
        return Sugestao(
            categoria=None,
            conta_debito=self._conta_fallback_debito,
            conta_credito=self._conta_fallback_credito,
            centro_custo=None,
            confidence=0.0,
            metodo="embedding",
            precisa_revisao=True,
            motivo="Sem histórico suficiente para classificação semântica.",
        )


def _texto_documento(documento: Documento) -> str:
    """Representa o documento como texto para embedding."""
    partes = []
    if documento.nome_emitente:
        partes.append(documento.nome_emitente)
    if hasattr(documento, "metadados_nfe") and documento.metadados_nfe:
        nfe = documento.metadados_nfe
        if isinstance(nfe, dict):
            partes.extend([
                str(nfe.get("cfop", "")),
                str(nfe.get("natureza_operacao", "")),
            ])
    return " ".join(p for p in partes if p).strip() or "SEM DESCRICAO"


def _produto_interno(a: list[float], b: list[float]) -> float:
    """Produto interno de dois vetores (similaridade do cosseno se normalizados)."""
    return sum(x * y for x, y in zip(a, b, strict=False))


def _sim_para_confidence(sim: float) -> float:
    """Mapeia similaridade [0, 1] para confidence [0, 1] com suavização."""
    # Clipa para [0, 1] e aplica raiz quadrada suave para evitar
    # confidence=1.0 mesmo quando sim=1.0 (só regras determinísticas
    # devem ter confidence=1.0)
    clipped = max(0.0, min(1.0, sim))
    return round(min(0.98, clipped ** 0.5), 4)
