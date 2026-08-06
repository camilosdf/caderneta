"""Policy Engine — separado do Rule Engine (recomendação do comitê).

Regras contábeis: o QUÊ classificar → Rule Engine
Políticas operacionais: QUEM aprova, QUANDO bloquear → Policy Engine

Exemplos de políticas:
- Valor > R$ 5.000 exige dois aprovadores
- Período fechado não aceita lançamentos
- Usuário só aprova lançamentos de outro usuário (segregação de funções)

Toda avaliação de política é registrada no audit log com a versão da
política que estava ativa — reproduzível em auditoria futura.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

_UTC = timezone.utc


def _agora_iso() -> str:
    return datetime.now(_UTC).isoformat() + "Z"
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4


class ResultadoPolitica(str, Enum):
    PERMITIDO   = "permitido"
    BLOQUEADO   = "bloqueado"
    REQUER_ACAO = "requer_acao"


@dataclass(frozen=True)
class AvaliacaoPolitica:
    """Resultado imutável de uma avaliação de política."""
    resultado: ResultadoPolitica
    politica_nome: str
    versao_politica: int
    motivo: str
    acao_requerida: str | None = None   # ex: "segundo aprovador"
    avaliado_em: str = field(default_factory=_agora_iso)
    avaliacao_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class Politica:
    """Uma política operacional versionada e auditável."""
    id: str = field(default_factory=lambda: str(uuid4()))
    nome: str = ""
    descricao: str = ""
    versao: int = 1
    ativa: bool = True
    criada_por: str = ""
    criada_em: datetime = field(default_factory=lambda: datetime.now(_UTC))
    valida_a_partir: datetime | None = None
    valida_ate: datetime | None = None


class PolicyEngine:
    """
    Avalia políticas operacionais sobre lançamentos e usuários.
    Completamente separado do Rule Engine — políticas não classificam,
    apenas controlam fluxo de aprovação e acesso.
    """

    def __init__(
        self,
        limite_aprovacao_simples: Decimal = Decimal("5000.00"),
    ):
        self._limite = limite_aprovacao_simples
        self._versao = 1

    def avaliar_aprovacao(
        self,
        valor_lancamento: Decimal,
        aprovador_id: str,
        criador_id: str,
        nivel_atual: int = 1,
    ) -> AvaliacaoPolitica:
        """
        Verifica se o aprovador pode aprovar este lançamento.
        Aplica segregação de funções e limites de valor.
        """
        # Política: segregação de funções
        if aprovador_id == criador_id:
            return AvaliacaoPolitica(
                resultado=ResultadoPolitica.BLOQUEADO,
                politica_nome="segregacao_funcoes",
                versao_politica=self._versao,
                motivo="O criador do lançamento não pode ser o mesmo aprovador.",
                acao_requerida="Designar aprovador diferente do criador.",
            )

        # Política: valor alto exige dois aprovadores
        if valor_lancamento > self._limite and nivel_atual < 2:
            return AvaliacaoPolitica(
                resultado=ResultadoPolitica.REQUER_ACAO,
                politica_nome="aprovacao_alto_valor",
                versao_politica=self._versao,
                motivo=f"Valor R$ {valor_lancamento:,.2f} acima do limite de "
                       f"R$ {self._limite:,.2f} — exige segundo aprovador.",
                acao_requerida="Encaminhar para aprovação de Supervisor.",
            )

        return AvaliacaoPolitica(
            resultado=ResultadoPolitica.PERMITIDO,
            politica_nome="aprovacao_padrao",
            versao_politica=self._versao,
            motivo="Aprovação dentro dos limites configurados.",
        )

    def avaliar_periodo(
        self,
        ano: int,
        mes: int,
        periodos_fechados: set[tuple[int, int]],
    ) -> AvaliacaoPolitica:
        """Verifica se o período contábil está aberto para lançamentos."""
        if (ano, mes) in periodos_fechados:
            return AvaliacaoPolitica(
                resultado=ResultadoPolitica.BLOQUEADO,
                politica_nome="periodo_contabil",
                versao_politica=self._versao,
                motivo=f"Período {mes:02d}/{ano} está fechado.",
                acao_requerida="Reabrir o período requer autorização de Supervisor.",
            )

        return AvaliacaoPolitica(
            resultado=ResultadoPolitica.PERMITIDO,
            politica_nome="periodo_contabil",
            versao_politica=self._versao,
            motivo=f"Período {mes:02d}/{ano} está aberto para lançamentos.",
        )

    def avaliar_pre_aprovacao(
        self,
        confidence: float,
        valor: Decimal,
        threshold_pre_aprovacao: float = 0.99,
    ) -> AvaliacaoPolitica:
        """Decide se um lançamento pode ser pré-aprovado automaticamente."""
        if confidence >= threshold_pre_aprovacao and valor <= self._limite:
            return AvaliacaoPolitica(
                resultado=ResultadoPolitica.PERMITIDO,
                politica_nome="pre_aprovacao_automatica",
                versao_politica=self._versao,
                motivo=f"Confiança {confidence:.0%} ≥ {threshold_pre_aprovacao:.0%} "
                       f"e valor dentro do limite.",
            )

        motivo_partes = []
        if confidence < threshold_pre_aprovacao:
            motivo_partes.append(f"confiança {confidence:.0%} abaixo do threshold")
        if valor > self._limite:
            motivo_partes.append(f"valor R$ {valor:,.2f} acima do limite")

        return AvaliacaoPolitica(
            resultado=ResultadoPolitica.REQUER_ACAO,
            politica_nome="pre_aprovacao_automatica",
            versao_politica=self._versao,
            motivo=f"Pré-aprovação bloqueada: {' e '.join(motivo_partes)}.",
            acao_requerida="Encaminhar para fila de revisão humana.",
        )
